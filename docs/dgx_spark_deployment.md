# Deploying the full platform on an NVIDIA DGX Spark

This runbook brings up the whole stack — PostgreSQL, the FastAPI platform API,
Celery workers, n8n automation, and Ollama — on a single DGX Spark, and then
verifies that a scheduled source refresh actually lands jobs in the database
and on the dashboard.

Everything binds to loopback. Nothing here exposes the box to the internet; see
[Caveats](#caveats) before changing that.

## 1. Assumptions

| Item | Expected |
| --- | --- |
| Hardware | DGX Spark (GB10, 128GB unified memory) |
| Architecture | `aarch64` |
| OS | DGX OS, with Docker Engine and the NVIDIA Container Toolkit preinstalled |
| Disk | ~150GB free (Ollama models dominate: `gpt-oss:120b` alone is ~65GB) |

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
for key in N8N_ENCRYPTION_KEY INTERNAL_SERVICE_TOKEN AUTH_PEPPER \
           POSTGRES_PASSWORD LANGGRAPH_POSTGRES_PASSWORD \
           N8N_POSTGRES_PASSWORD MINIO_SECRET_KEY; do
  printf '%s=%s\n' "$key" "$(openssl rand -hex 32)"
done
```

Then set the model and (optionally) the Apify token:

```ini
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_CHAT_MODEL=gpt-oss:120b
OLLAMA_EMBEDDING_MODEL=embeddinggemma
APIFY_TOKEN=<your apify token, or leave empty>
```

> **Set `N8N_ENCRYPTION_KEY` before the first `docker compose up`.** n8n uses it
> to encrypt stored credentials; rotating it later makes existing workflow
> credentials unreadable.

Leaving `OLLAMA_CHAT_MODEL` empty is a valid configuration — the platform runs
with the disabled model provider, and enrichment plus match explanations are
reported as degraded rather than failing.

## 3. Bring up the stack

```bash
docker compose --profile platform --profile automation --profile ai build
docker compose --profile platform --profile automation --profile ai up -d
docker compose ps
```

The `migrate` service runs `alembic upgrade head` automatically and must exit
`0` before `app` and the workers start; compose enforces that ordering.

## 4. Pull the Ollama models

```bash
docker compose exec ollama ollama pull gpt-oss:120b
docker compose exec ollama ollama pull embeddinggemma
```

`gpt-oss:120b` is ~65GB in MXFP4 and fits in the Spark's 128GB unified memory
alongside the rest of the stack. If first-token latency is more annoying than
answer quality is valuable, `llama3.3:70b` or `qwen3:32b` are drop-in swaps —
change `OLLAMA_CHAT_MODEL` and restart (step 6).

`embeddinggemma` outputs 768 dimensions, which must match `EMBEDDING_DIMENSION`.
The embedding write path checks the length and silently skips vectors of any
other size, so a mismatched model produces a system with no embeddings and no
error.

Verify the model is live:

```bash
curl -s localhost:8000/health/ready | python3 -m json.tool
# expect: "available": true  and  "degraded": false
```

## 5. Import and activate the n8n workflows

```bash
python scripts/validate_n8n_workflows.py
python scripts/import_n8n_workflows.py
```

Open <http://localhost:5678>, create the owner account on first login, then
activate the workflows. Either toggle each one in the UI, or:

```bash
docker compose exec n8n n8n update:workflow --all --active=true
docker compose restart n8n n8n-worker
```

The restart is required: in queue mode, schedule registration happens at
startup, so workflows activated via the CLI do not begin firing until n8n
restarts.

## 6. Restarting after an `.env` change

Settings are `lru_cache`d per process, so editing `.env` has no effect on a
running container:

```bash
docker compose restart app worker-interactive worker-batch worker-ingest dashboard
```

## 7. End-to-end verification

Work through these in order; each one builds on the last.

**1. Services healthy.** `docker compose ps` shows every service healthy or
running, and `migrate` exited `0`.

**2. Model ready.** `curl -s localhost:8000/health/ready` reports
`model.available: true`.

**3. A real refresh runs.** In the n8n UI, open **company-careers-refresh** and
click *Execute Workflow*. The HTTP node should return:

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

**4. Dashboard reads Postgres.** <http://localhost:8010> renders job cards with
track badges and source attribution, and `/api/health` reports `job_count > 0`.
Those badges come from the `job_json` payload, so a populated dashboard is also
proof the new column is being written.

**5. Idempotency holds.** Re-execute the same workflow within the hour. The
stored response comes back unchanged and `worker-ingest` starts no second crawl.

**6. Apify path.** With `APIFY_TOKEN` set, the apify node of
**future-sources-refresh** produces a `SourceRun` carrying
`apify_linkedin_health` metadata. With the token empty it returns
`{"status": "disabled", "reason": "APIFY_TOKEN is not configured"}`. The
`ksbit_denodo` node in the same workflow always returns `disabled` — it has no
approved endpoint mapping, and that is the expected result, not a failure.

**7. Failure path.** Set a bogus `APIFY_TOKEN`, restart the workers, and run the
apify node. Expect a `failed` row in `source_runs`, then:

```bash
curl -s -H "Authorization: Bearer $INTERNAL_SERVICE_TOKEN" \
     -H "Idempotency-Key: $(uuidgen)" -H "X-Request-ID: $(uuidgen)" \
     localhost:8000/internal/v1/alerts/source-health
# expect: {"status": "attention", "failures": [...]}
```

The **source-health-alerts** workflow should then fail loudly on its next run.
Restore the real token afterwards.

**8. Tests pass.**

```bash
pytest                                    # unit + integration
pytest -m postgres                        # requires the stack to be up
```

## Caveats

- **n8n stays on loopback.** It is bound to `127.0.0.1:5678` and is deliberately
  absent from the `edge` profile. It has no per-user authorization model beyond
  its owner account, and its workflows hold an internal service token that can
  trigger crawls and read every student's data. Reach it over an SSH tunnel, not
  a tunnel to the internet.
- **The `observability` profile is off by default.** `arizephoenix/phoenix` has
  not been verified on arm64. Every other pinned image in the compose file is
  multi-arch. Verify Phoenix before enabling that profile on the Spark.
- **Redis database map.** DB `0` is Celery's broker and result backend; DB `2`
  is the n8n queue. Do not point another service at either.
- **`full_refresh` is off for scheduled runs.** A full refresh marks any posting
  absent from the run as inactive. When one company's ATS fails mid-crawl, that
  would deactivate all of its live jobs, so the scheduler always requests an
  incremental run. Use `--full-refresh` on the CLI runner only after confirming
  every company in the config succeeded.
- **Backups.** `pg_dump` the platform database plus the `hope_pgdata`,
  `hope_n8n`, and `hope_minio` volumes. The n8n volume is worthless without the
  matching `N8N_ENCRYPTION_KEY` — back that up with it, separately.

## Layout reference

| Service | Port (loopback) | Profile |
| --- | --- | --- |
| `app` (platform API) | via `caddy`/`web` | `platform` |
| `dashboard` | 8010 | `platform` |
| `postgres` | 5432 | (always) |
| `n8n` | 5678 | `automation` |
| `ollama` | 11434 | `ai` |
| `minio` console | 9001 | (always) |
| `grafana` | 3001 | `observability` |
| `prometheus` | 9090 | `observability` |

Celery queues: `interactive` (coach), `batch` (enrichment, matching, retention),
`ingest` (source crawls, one at a time, 90-minute ceiling).
