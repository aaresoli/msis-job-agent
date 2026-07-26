# Deploying the full platform on an NVIDIA DGX Spark

This runbook brings up the whole stack — PostgreSQL, the FastAPI platform API,
Celery workers, the scheduler, and Ollama — on a single DGX Spark, and then
verifies that a scheduled source refresh actually lands jobs in the database
and are served by the platform API's discovery endpoints.

Everything binds to loopback. Nothing here exposes the box to the internet; see
[Caveats](#caveats) before changing that.

## 1. Assumptions

| Item | Expected |
| --- | --- |
| Hardware | DGX Spark (GB10, 128GB unified memory) |
| Architecture | `aarch64` |
| OS | DGX OS, with Docker Engine and the NVIDIA Container Toolkit preinstalled |
| Disk | ~150GB free (Ollama models dominate: ~80GB for the three below) |

Confirm the GPU is visible from inside a container before going further:

```bash
uname -m                      # expect aarch64
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi
```

If `nvidia-smi` fails inside the container, stop and fix the container toolkit
first — the `ai` profile will not work without it.

## 2. Clone and configure

```bash
git clone <repo-url> msis-job-agent
cd msis-job-agent
cp .env.example .env
```

Generate a distinct secret for each of these and paste them into `.env`:

```bash
for key in INTERNAL_SERVICE_TOKEN AUTH_PEPPER \
           POSTGRES_PASSWORD LANGGRAPH_POSTGRES_PASSWORD \
           PHOENIX_POSTGRES_PASSWORD MINIO_SECRET_KEY; do
  printf '%s=%s\n' "$key" "$(openssl rand -hex 32)"
done
```

Then set the model and (optionally) the Apify token:

```ini
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_CHAT_MODEL=gpt-oss:120b
OLLAMA_INTERACTIVE_MODEL=gpt-oss:20b
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_MAX_LOADED_MODELS=3
OLLAMA_NUM_PARALLEL=4
OLLAMA_FLASH_ATTENTION=true
OLLAMA_KV_CACHE_TYPE=q8_0
OLLAMA_NUM_CTX=16384
OLLAMA_INTERACTIVE_NUM_CTX=8192
OLLAMA_BATCH_REASONING=
OLLAMA_INTERACTIVE_REASONING=medium
APIFY_TOKEN=<your apify token, or leave empty>
```

> **Point `SMTP_HOST` somewhere before going further.** Magic links and student
> digests both send through it. For a local bring-up, `SMTP_HOST=mailpit`,
> `SMTP_PORT=1025`, `SMTP_STARTTLS=false` sends into the mailpit container and
> the messages are readable at <http://localhost:8025>. Leaving it empty is a
> supported configuration -- mail is simply disabled -- but then no one can sign
> in.

Leaving `OLLAMA_CHAT_MODEL` empty is a valid configuration — the platform runs
with the disabled model provider, and enrichment plus match explanations are
reported as degraded rather than failing.

## 3. Bring up the stack

```bash
docker compose --profile platform --profile ai --profile observability build
docker compose --profile platform --profile ai --profile observability up -d
docker compose ps
```

The `migrate` service runs `alembic upgrade head` automatically and must exit
`0` before `app` and the workers start; compose enforces that ordering.

## 4. The Ollama models

The `ai` profile includes a `model-init` one-shot that pulls exactly the models
named in `.env` and exits, and the workers wait for it, so on a normal bring-up
there is nothing to do here — watch it instead:

It does not warm them. Loading 65GB of weights only to have them evicted before
the first real request costs minutes and buys nothing; `OLLAMA_KEEP_ALIVE` is
what keeps a model resident once real work starts arriving.

```bash
docker compose logs -f model-init
```

Pull by hand only when adding a model outside the configured three:

```bash
docker compose exec ollama ollama pull gpt-oss:120b     # ~65GB, slow
docker compose exec ollama ollama pull gpt-oss:20b      # ~13GB
docker compose exec ollama ollama pull embeddinggemma
```

### Why these models

The Spark is bound by **memory bandwidth (~273 GB/s), not capacity**. Token
generation reads the active weights once per token, so what governs throughput
is *active* parameters — which makes MoE-vs-dense a far bigger factor than any
quality difference between candidates:

| Model | Type | Active params | Measured on this hardware |
| --- | --- | --- | --- |
| `llama3.3:70b` | dense | 70B | ~2.7 tok/s |
| `qwen3:32b` | dense | 32B | ~13 tok/s |
| `gpt-oss:120b` | MoE | 5.1B | ~40 tok/s |
| `gpt-oss:20b` | MoE | 3.6B | ~82 tok/s |
| `qwen3:30b-a3b` | MoE | ~3B | ~89 tok/s |

A dense model is therefore **not** a smaller-and-faster swap for `gpt-oss:120b`;
`llama3.3:70b` is roughly 15x slower despite being the smaller download. If the
120b is too slow, move to another MoE — `qwen3:30b-a3b` — not to a dense model.

The split follows the Celery queues: `OLLAMA_CHAT_MODEL` serves the `batch`
queue (enrichment, matching, Market Pulse, resume parsing) where quality
against the evidence-quote and citation contracts matters most, and
`OLLAMA_INTERACTIVE_MODEL` serves the coach, where a student is watching tokens
arrive. Leaving the interactive model empty is valid — the coach falls back to
the batch model.

**`OLLAMA_MAX_LOADED_MODELS` must be at least 3** (both chat models plus the
embedding model). Ollama evicts one model to load another by default, so
without this the split is worse than a single model: every queue switch pays a
multi-minute reload. All three together are ~78GB, which fits alongside
Postgres, Redis, and MinIO.

### Why concurrency, and what it costs

The same bandwidth argument that picks an MoE model also says to run more than
one request at a time. A single-stream decode reads the active weights once per
token and leaves the rest of the machine idle; concurrent sequences amortize
that same read across the batch. **Ollama defaults `OLLAMA_NUM_PARALLEL` to 1**,
so a stock deployment serves the enrichment backlog one job at a time no matter
how much memory is free.

Slots are paid for in KV cache, and that is the whole difficulty. Measured on
this hardware, `gpt-oss:120b` reserved **16GB of KV for a single 32768-token
slot** — four of those does not fit beside 65GB of weights. The three settings
therefore move together:

| Setting | Value | Why |
| --- | --- | --- |
| `OLLAMA_FLASH_ATTENTION` | `true` | Prefill win on long descriptions; required before KV quantization |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Roughly halves KV per slot. Not `q4_0`: evidence quotes must come back verbatim |
| `OLLAMA_NUM_CTX` | `16384` | Postings and the ~30k-char batch prompts sit under this; halving it halves KV again |
| `OLLAMA_NUM_PARALLEL` | `4` | The slots the three settings above pay for |

Budget at those values: ~65GB weights + ~16GB KV (4 slots) + ~14GB for
`gpt-oss:20b` + ~1GB embeddings ≈ 96GB of the 116GB the GPU reports. Verify
after changing them and drop to `OLLAMA_NUM_PARALLEL=2` if the 120b starts
evicting the interactive model:

```bash
docker compose logs ollama | grep "runner.go.*load request"   # expect Parallel:4
curl -s localhost:11434/api/ps | python3 -m json.tool          # expect all three resident
```

`worker-batch` runs one Celery child per slot (`--concurrency` is wired to
`OLLAMA_NUM_PARALLEL`). Raising it higher does not add throughput — it moves the
queue out of Celery, where it is visible, into Ollama, where it is not.

#### What the concurrency actually bought

Same 40-posting backlog of real crawled postings (~6.5k characters each),
re-enriched end to end, code identical, only the tuning changed:

| Configuration | Per posting | Accepted |
| --- | --- | --- |
| `NUM_PARALLEL=1`, f16 KV, 32k ctx | 24.0s | 36/40 |
| `NUM_PARALLEL=4`, q8_0 KV, 16k ctx | 17.2s | 36/40 |
| …plus `OLLAMA_BATCH_REASONING=low` | 9.4s | **33/40** |

**Concurrency is the free part**: 1.4x with acceptance unchanged. The per-call
telemetry shows why it is 1.4x and not 4x — under 4-way concurrency each
request decodes at ~11–20 tok/s instead of the ~40 tok/s a single stream gets.
Per-sequence rate falls, aggregate rises; that is the shape of batched decode,
not a regression.

**Reasoning effort is the part with a bill.** It is nearly another 2x, and it
costs three postings in forty — each one a posting a human now has to review.
That is why the shipped default is empty. Decide it against your own corpus and
your reviewers' time, not against the gold set, which scores 12/12 either way
and cannot see this at all.

Measure both, always on the same backlog:

```bash
docker compose logs worker-batch | grep "local inference"
```

On a smaller machine, note that the same knob behaves *worse* on `gpt-oss:20b`
(see the table above): faster still, and it starts paraphrasing evidence quotes
outright.

### Reasoning effort

`gpt-oss` reasons on every call whether or not anything reads the result, and
`provider.chat()` returns `message.content` while discarding `message.thinking`.
On the extraction paths those tokens are decode time spent on output nobody
sees, so lowering the effort looks like free throughput.

It is not free, and `OLLAMA_BATCH_REASONING` therefore ships **empty**. See the
40-posting table above: `low` is worth nearly 2x and costs three postings in
forty to the review queue. The coach keeps `medium` — it is a judgement task,
and nobody is waiting on a batch queue behind it.

The benchmark below is necessary but **not sufficient** for this decision. Run
it, then re-run a real backlog:

```bash
python scripts/evaluate_local_models.py gpt-oss:120b gpt-oss:20b \
    --reasoning low --verbose
```

Measured on this hardware over the 12 committed gold postings, one request at a
time:

| Model | Reasoning | 1st token | chunks/s | Schema accepted |
| --- | --- | --- | --- | --- |
| `gpt-oss:120b` | default | 12.97s | 3.2 | 12/12 |
| `gpt-oss:120b` | `low` | 12.77s | 3.5 | 12/12 |
| `gpt-oss:20b` | default | 7.24s | 5.2 | 12/12 |
| `gpt-oss:20b` | `low` | 5.42s | 7.9 | **11/12** |

Two things to take from this table, one of them a warning about the table
itself.

The 20b row is the obvious lesson: it gets ~50% faster at `low` and then
paraphrases an evidence quote instead of copying it — the exact failure
`_unsupported_quotes` exists to catch. Leave the effort alone on that model.

The subtler lesson is that **the 120b rows are misleading**. They say `low`
costs nothing (12/12 either way), and on real postings it costs 3 in 40. The
gold postings are short summaries; the quote check gets harder as a posting
gets longer, and 12 clean examples cannot see it. Treat this benchmark as a
fast smoke test for a model swap, and treat a real backlog as the evidence for
a quality setting.

`embeddinggemma` outputs 768 dimensions, which must match `EMBEDDING_DIMENSION`.
A mismatched model now logs a warning and discards the vector rather than
skipping silently, but the result is still a system with no embeddings — check
the worker logs for `check OLLAMA_EMBEDDING_MODEL` if similarity search returns
nothing.

Verify the models are live:

```bash
curl -s localhost:8000/health/ready | python3 -m json.tool
# expect: "available": true  and  "degraded": false
```

The readiness check verifies that the configured chat *and* embedding models are
actually installed, not just that Ollama answers — a typo in a model name
reports `available: false` with the offending name in `detail`.

Confirm both chat models stay resident after exercising the coach and an
enrichment job:

```bash
curl -s localhost:11434/api/ps | python3 -m json.tool
```

Both should be listed at once. If one evicts the other,
`OLLAMA_MAX_LOADED_MODELS` did not take effect.

## 5. Confirm the scheduler is running

There is nothing to import or activate. The schedule is compiled into the
application (`src/hope_job_agent/workers/schedules.py`) and the `beat` service
starts with the `platform` profile.

```bash
docker compose logs beat | grep -i "Scheduler: Sending"
```

Within a minute you should see `hope.ops.heartbeat`, `hope.ops.export_metrics`
and `hope.ops.relay_outbox` being dispatched. The heartbeat is what the
`HopeBeatDown` alert watches: beat has no health endpoint and no ping, so a
dead scheduler would otherwise look exactly like a quiet night.

To see what is scheduled, and when each entry next fires:

```bash
docker compose exec beat python -c "
from hope_job_agent.workers.schedules import BEAT_SCHEDULE
for name, entry in BEAT_SCHEDULE.items():
    print(f'{name:28} {entry[\"task\"]:32} {entry[\"schedule\"]}')
"
```

Nothing needs to be enabled for the schedule to take effect, which is the point:
the previous n8n workflows shipped inactive and only existed inside the
container after a manual import, so in practice nothing ran at all.

## 6. Restarting after an `.env` change

Settings are `lru_cache`d per process, so editing `.env` has no effect on a
running container:

```bash
docker compose restart app beat worker-interactive worker-batch worker-ingest worker-ops
```

## 7. End-to-end verification

Work through these in order; each one builds on the last.

**1. Services healthy.** `docker compose ps` shows every service healthy or
running, and `migrate` exited `0`.

**2. Model ready.** `curl -s localhost:8000/health/ready` reports
`model.available: true`.

**2a. Inference is instrumented.** Every non-streaming call logs its own
counters, which is how throughput and eviction become observable rather than
inferred:

```bash
docker compose logs worker-batch | grep "local inference"
# local inference model=gpt-oss:120b workload=batch op=chat prompt_tokens=205 \
#   generated_tokens=55 tok_per_s=16.0 load_s=0.21
```

A `load_s` in the tens of seconds on a warm queue means a model was evicted and
reloaded — check `OLLAMA_MAX_LOADED_MODELS` and the memory budget above. The
same numbers are Prometheus counters (`hope_llm_*`). They are exported by the
worker that produced them, on `:9100` — not by the API, which never runs
these calls:

```bash
docker compose exec worker-batch curl -s localhost:9100/metrics | grep hope_llm
```

**3. A real refresh runs.** Rather than waiting for the four-hourly window,
trigger the same task the scheduler dispatches:

```bash
docker compose exec worker-ops celery \
  -A hope_job_agent.workers.celery_app:celery_app \
  call hope.sources.refresh_all
```

The operator endpoint does the same thing and returns:

```json
{"source": "company_careers", "status": "accepted", "task_id": "..."}
```

Watch the crawl and then confirm it landed:

```bash
docker compose logs -f worker-ingest
```

```sql
SELECT source_name, run_status, jobs_inserted, jobs_updated, errors_count
FROM source_runs ORDER BY started_at DESC LIMIT 5;

SELECT count(*) FROM job_postings WHERE job_json IS NOT NULL;
```

**3a. Descriptions are plain text.** Check this before trusting any enrichment
or similarity result, because the description is what gets embedded, what the
enrichment model reads, and what a student sees:

```sql
SELECT split_part(source_detail, ':', 1) AS provider,
       count(*) AS total,
       count(*) FILTER (WHERE description ~ '<[a-zA-Z/][^>]*>') AS with_html
FROM job_postings WHERE source = 'company_careers' GROUP BY 1;
```

`with_html` must be `0` for every provider. A non-zero count means an ATS is
returning markup that `clean_html` did not reduce — Greenhouse, for instance,
returns HTML that is itself entity-encoded, which defeated a single
strip-then-unescape pass and left every one of its postings tagged. The
symptom downstream is not obviously an ingestion problem: enrichment starts
routing long postings to review, because the model quotes the *rendered*
salary while the stored text still holds the surrounding spans.

**3b. Enrichment acceptance is sane.** 

```sql
SELECT status, count(*), round(avg(length(p.description))) AS avg_chars
FROM job_enrichments e JOIN job_postings p ON p.id = e.job_id GROUP BY 1;
```

A `review` share that climbs with description length points at the quote check,
not at the model. Note that the reason a posting was rejected is *not*
persisted — re-run the graph over the offending posting to see it.

**4. Discovery API reads Postgres.** `GET /api/v1/discovery/stats` reports a
non-zero job count, and `GET /api/v1/discovery/jobs` returns cards carrying
track and source-attribution facets. Those facets come from the `job_json`
payload, so a populated response is also proof the new column is being written.

**5. Idempotency holds.** Re-execute the same request within the hour, reusing
its `Idempotency-Key`. The stored response comes back unchanged and
`worker-ingest` starts no second crawl.

**6. Apify path.** With `APIFY_TOKEN` set, executing the `apify_linkedin`
source produces a `SourceRun` carrying `apify_linkedin_health` metadata:

```bash
curl -s -X POST -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" \
     -H "Idempotency-Key: $(uuidgen)" -H "X-Request-ID: $(uuidgen)" \
     -H "Content-Type: application/json" -d '{"limit": 5}' \
     localhost:8000/internal/v1/sources/apify_linkedin/execute
```

With the token empty it returns
`{"status": "disabled", "reason": "APIFY_TOKEN is not configured"}`. The
`ksbit_denodo` source always returns `disabled` — it has no approved endpoint
mapping, and that is the expected result, not a failure.

The scheduled equivalent is the `hope.sources.refresh_all` beat task, which
sweeps every approved source every four hours under a single-flight lock.

**7. Failure path.** Set a bogus `APIFY_TOKEN`, restart the workers, and execute
the source again. Expect a `failed` row in `source_runs`, then:

```bash
curl -s -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" \
     -H "X-Request-ID: $(uuidgen)" \
     localhost:8000/internal/v1/alerts/source-health
# expect: {"status": "attention", "failures": [...]}
```

That endpoint is what replaced the source-health-alerts workflow; Prometheus
alerts on the same underlying `source_runs` state. Restore the real token
afterwards.

**8. Tests pass.**

```bash
pytest                                    # unit + integration
pytest -m postgres                        # requires the stack to be up
```

## 8. Alerting

The `observability` profile loads `infra/prometheus/rules/hope.yml` and routes
firing alerts through Alertmanager to SMTP — the same relay the platform uses
for digests, so locally they land in mailpit alongside everything else.

```bash
open http://localhost:9090/alerts       # rule state
open http://localhost:9093              # Alertmanager
```

The rules cover the failures that are otherwise silent: a dead scheduler, a
stale or unverified backup, an outbox that has stopped draining, source runs
failing, a queue that never drains, model eviction, and API 5xx. Prove the path
works before trusting it:

```bash
docker compose stop worker-ingest       # wait ~5 minutes
open http://localhost:9090/alerts       # HopeServiceDown firing
open http://localhost:8025              # the alert mail
docker compose start worker-ingest
```

## 9. Start on boot

Docker is enabled at boot on DGX OS; the compose stack is not, so a reboot
leaves the platform down until someone notices. Install the unit:

```bash
sudo cp infra/systemd/hope-platform.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hope-platform
systemctl status hope-platform
```

Edit `WorkingDirectory` and the profile list in the unit first if the checkout
lives elsewhere or the deployment does not want a profile. `edge` is
deliberately absent: publishing the stack through a Cloudflare tunnel must be
an explicit act, not something a power cycle turns on.

## Caveats

- **One scheduler, exactly one replica.** `beat` dispatches; it does not
  execute. Running two of them fires every scheduled task twice. The
  `hope.ops.backup` and `hope.sources.refresh_all` tasks additionally take a
  Redis single-flight lock, so a manual trigger cannot stack on top of a
  scheduled run — but that lock is a backstop, not a licence to scale `beat`.
- **The `observability` profile is off by default.** `arizephoenix/phoenix` has
  not been verified on arm64. Every other pinned image in the compose file is
  multi-arch. Verify Phoenix before enabling that profile on the Spark.
- **Redis database map.** DB `0` is Celery's broker and result backend. Do not
  point another service at it.
- **`full_refresh` is off for scheduled runs.** A full refresh marks any posting
  absent from the run as inactive. When one company's ATS fails mid-crawl, that
  would deactivate all of its live jobs, so the scheduler always requests an
  incremental run. Use `--full-refresh` on the CLI runner only after confirming
  every company in the config succeeded.
- **Upgrading from a pre-PostgreSQL-18 deployment.** Two things changed at
  once: the major version, and the data directory (pg18 uses
  `/var/lib/postgresql/18/docker`, so `hope_pgdata` now mounts at
  `/var/lib/postgresql`). A host on an earlier compose revision must dump
  before pulling this one and restore afterwards. The procedure is the comment
  above the `postgres` service in `docker-compose.yml` — it is kept there
  rather than duplicated here so an operator editing the image tag cannot miss
  it. It is a dump/restore with downtime, not a rolling upgrade.
- **Backups run themselves, and verify themselves.** `hope.ops.backup` fires
  nightly at 01:00: it dumps `hope_jobs` plus cluster roles, uploads the
  archive to the `hope-backups` MinIO bucket, restores it into a scratch
  database to confirm it is loadable, and prunes past
  `BACKUP_RETENTION_DAYS`. Check the last result with:

  ```bash
  curl -s -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" \
    localhost:8000/internal/v1/backup/verified | python3 -m json.tool
  ```

  `verified: false` is the state to act on — it means the archive exists but
  did not restore, which looks like protection and is not. The archives live in
  MinIO, so `hope_minio` is the volume that must survive the machine; copy it
  off the Spark.

## Layout reference

| Service | Port (loopback) | Profile |
| --- | --- | --- |
| `app` (platform API) | via `caddy`/`web` | `platform` |
| `postgres` | 5432 | (always) |
| `ollama` | 11434 | `ai` |
| `minio` console | 9001 | (always) |
| `grafana` | 3001 | `observability` |
| `prometheus` | 9090 | `observability` |
| `alertmanager` | 9093 | `observability` |
| `mailpit` (dev mail sink) | 8025 | `dev` (override file) |

Celery queues: `interactive` (coach), `batch` (enrichment, matching),
`ingest` (source crawls, one at a time, 3-hour ceiling), `ops` (outbox relay,
digests, backups, reconciliation, retention, metric sampling).

The `ops` queue is separate so a thirty-second outbox relay never waits behind
a GPU-bound enrichment backlog or an hour-long ATS crawl. Every worker also
serves its Prometheus metrics on `:9100`.
