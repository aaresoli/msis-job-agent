# DGX Spark deployment: vLLM + TEI

This is the production runbook for local inference on the NVIDIA DGX Spark.
The stack uses one continuously batched `openai/gpt-oss-120b` vLLM engine for
both batch and coach work, plus Hugging Face Text Embeddings Inference (TEI)
serving `google/embeddinggemma-300m` on ARM64 CPU. No hosted inference provider
is configured.

The [TEI ARM64 release alias documented upstream is currently unpublished](https://github.com/huggingface/text-embeddings-inference/issues/900), so Compose pins the verified TEI 1.9.3 ARM64 commit image and index digest. The images and flags otherwise follow the current [NVIDIA DGX Spark vLLM guide](https://build.nvidia.com/spark/vllm/instructions), [vLLM server CLI](https://docs.vllm.ai/en/stable/cli/serve/), and [TEI ARM64 support matrix](https://huggingface.co/docs/text-embeddings-inference/en/supported_models).

## Why this layout

- One 120B engine avoids model eviction and uses vLLM continuous batching.
- Coach and batch requests share weights. `priority=-10` for coach and `0` for
  batch keeps interactive work ahead of a backlog without a second model.
- The server has eight sequence slots while the batch worker submits four at a
  time, leaving admission room for interactive traffic.
- Chunked prefill prevents long job descriptions from monopolizing an engine
  step. Prefix caching reuses stable extraction instructions.
- `max-model-len=16384` covers current posting, resume, and market prompts while
  bounding KV-cache growth.
- EmbeddingGemma remains 768-dimensional, so the existing pgvector schema does
  not change. TEI batches up to 32 inputs on CPU and leaves the GPU budget to
  GPT-OSS.
- Speculative decoding is intentionally off until it passes the evidence-quote
  and JSON-schema acceptance gates below.

## One-time prerequisites

1. Confirm Docker, Compose, the NVIDIA driver, and container toolkit:

   ```bash
   uname -m                       # aarch64
   nvidia-smi
   docker version
   docker compose version
   docker run --rm --gpus all nvcr.io/nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi
   ```

2. Log into NVIDIA NGC if the vLLM image is not already accessible:

   ```bash
   docker login nvcr.io
   ```

3. In Hugging Face, accept the EmbeddingGemma license and create a read-only
   token. Store it as an ignored Docker-secret file, never in `.env`:

   ```bash
   install -d -m 700 secrets
   install -m 600 /dev/null secrets/hf_token
   # Open secrets/hf_token in your editor and paste only the token.
   ```

4. Create `.env` and replace every development secret before shared use:

   ```bash
   cp .env.example .env
   docker compose --profile platform --profile ai config --quiet
   ```

The AI defaults in `.env.example` are the tested Spark starting point. Model
weights are cached in the `hope_huggingface` named volume across restarts.

## Cold start and zero-surprise cutover

Start the new servers first. Their loopback ports (`8001` and `8002`) do not
conflict with an existing Ollama process on `11434`:

```bash
docker compose --profile ai pull vllm embed
docker compose --profile ai up -d vllm embed
docker compose logs -f vllm embed
```

First download and load can take tens of minutes. Wait for both checks:

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/v1/models | jq
curl -fsS http://127.0.0.1:8002/health
curl -fsS http://127.0.0.1:8002/info | jq
```

Probe a 768-dimensional embedding:

```bash
curl -fsS http://127.0.0.1:8002/v1/embeddings   -H 'Content-Type: application/json'   -d '{"model":"google/embeddinggemma-300m","input":["task: search result | query: data analyst"]}'   | jq '.data[0].embedding | length'
# expected: 768
```

Run the production-contract benchmark before routing the app:

```bash
uv run python scripts/evaluate_local_models.py   --base-url http://127.0.0.1:8001   --embedding-base-url http://127.0.0.1:8002   openai/gpt-oss-120b
```

Then recreate model-consuming application services. Ingest, operations, and
Beat do not wait for model startup:

```bash
docker compose --profile platform --profile ai up -d --build   app worker-interactive worker-batch worker-ingest worker-ops beat web
curl -fsS http://127.0.0.1:8000/health/ready | jq
```

The provider degrades safely if either server is unavailable: extraction goes
to review, coach streaming returns its existing unavailable message, and
vector retrieval is skipped rather than failing the API.

## Full re-index after migration

Ollama and TEI vector spaces are not interchangeable even when both are 768
dimensions. The nightly reconciler now detects missing vectors, a different
model ID, changed job text, and changes to the canonical EmbeddingGemma prompt.
Trigger it immediately after cutover:

```bash
docker compose exec worker-ops   celery -A hope_job_agent.workers.celery_app:celery_app   call hope.ops.reconcile --queue ops
```

Watch the batch queue and verify every active job uses the new model:

```bash
docker compose logs -f worker-batch embed
docker compose exec postgres psql -U "${POSTGRES_USER:-hope_user}"   -d "${POSTGRES_DB:-hope_jobs}" -c   "select embedding_model, count(*) from job_embeddings group by embedding_model;"
```

Do not delete the old Ollama volume until this query, matching, and rollback
validation are complete.

## Acceptance gates

The migration is accepted only when all of these pass:

- Committed gold set: 12/12 enrichment records reach `ready`.
- The same 40-post production sample used for the Ollama baseline: at least
  36/40 reach `ready` and mean wall time is at most 13.8 seconds per posting
  (20% faster than the recorded 17.2-second baseline).
- Coach P95 time to first token is below the recorded 7.24-second baseline while
  four batch requests remain in flight.
- The embedding probe returns 768 values and all active postings are re-indexed
  under `google/embeddinggemma-300m`.
- During a 30-minute mixed workload: no container restart/OOM, no increase in
  `vllm:num_preemptions_total`, and KV cache does not remain above 95%.

Prometheus scrapes vLLM on `vllm:8000`, TEI metrics on `embed:9000`, and HOPE
client counters from the workers. Grafana provisions **HOPE / Local AI — vLLM
and TEI** with TTFT, inter-token latency, queue depth, KV usage, throughput,
preemptions, availability, and request failures.

## Tuning order

Change one group at a time and repeat the acceptance workload:

1. If there is an OOM or preemption, lower `VLLM_GPU_MEMORY_UTILIZATION` from
   `0.82` to `0.78`, then lower `VLLM_MAX_NUM_SEQS` from `8` to `6`.
2. If long prefills delay the coach, lower `VLLM_MAX_NUM_BATCHED_TOKENS` from
   `8192` to `4096`; keep chunked prefill and priority scheduling enabled.
3. If the GPU is healthy but batch throughput is low, raise
   `VLLM_BATCH_CONCURRENCY` only up to the server sequence limit while retesting
   coach P95 latency.
4. Raise `VLLM_MAX_MODEL_LEN` only after measuring real prompt lengths; it
   directly increases worst-case KV demand.
5. Change reasoning effort only with schema/evidence acceptance results. The
   previous `low` experiment was faster but sent 3 additional posts per 40 to
   review, so batch defaults to the model setting and coach uses `medium`.

## Operations and security

```bash
# Native metrics
curl -fsS http://127.0.0.1:8001/metrics | head

# Engine and embedding logs
docker compose logs --since 30m vllm embed

# GPU/memory view
nvidia-smi
free -h
```

Model endpoints bind only to `127.0.0.1` on the host and remain private service
names inside Compose. Do not publish them through Caddy or Cloudflare. The HF
token is mounted as `/run/secrets/hf_token`; it is not part of image layers or
normal container environment inspection.

The systemd unit at `infra/systemd/hope-platform.service` starts platform, AI,
observability, and development mail profiles after reboot and allows one hour
for a cold model load.

## Rollback and final Ollama cleanup

Keep the prior application image/release and Ollama volume during the acceptance
window. If a gate fails, deploy the prior release configuration and point its
application variables back to `http://ollama:11434`; the database is compatible,
but re-index again because embedding spaces differ.

After all gates pass, remove orphaned Ollama containers with the normal Compose
cutover:

```bash
docker compose --profile platform --profile ai --profile observability   up -d --remove-orphans
```

The old named volume is intentionally not removed automatically. Deleting it is
irreversible and should happen only after the rollback window under the normal
backup/change-control process.
