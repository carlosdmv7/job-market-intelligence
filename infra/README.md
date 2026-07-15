# infra

Local + deployment scaffolding. The default stack is 0€.

## Local (Docker Compose)

Brings up **Ollama** (local LLM) + the **Streamlit app**. The warehouse is
MotherDuck (cloud free tier), so it isn't a container.

```bash
docker compose -f infra/docker-compose.yml up --build
# first run only: pull the model into the ollama volume
docker compose -f infra/docker-compose.yml exec ollama ollama pull qwen2.5:7b
# app -> http://localhost:8501
```

`motherduck_token` and `JMI_DUCKDB_DATABASE` are read from your shell env / `.env`.

## Images

- `docker/app.Dockerfile` — Streamlit app (`uv sync --package jmi-app`).
- `docker/worker.Dockerfile` — Prefect worker for the ingest/enrich flows.

## Orchestration

What actually schedules this project is **GitHub Actions**
(`.github/workflows/pipeline.yml`): a daily `ingest → enrich → dbt build`, the
0€ substitute for an always-on worker. The flows are Prefect-instrumented, so
every run — scheduled or manual `make` — reports state and logs to Prefect
Cloud.

`../orchestration/prefect.yaml` documents the worker-based path (deployments +
`jmi-pool` + `worker.Dockerfile`) for when an always-on machine is available;
it is deliberately not deployed today because that machine wouldn't be free.

## AWS notes (improvement section)

- Worker on a small EC2 (or ECS Fargate task) using `worker.Dockerfile`.
- Secrets via SSM Parameter Store / Secrets Manager → injected as env vars.
- The app deploys free to Streamlit Community Cloud, or as an ECS service.
- Ollama needs RAM/GPU; for a server deployment, Gemini free tier
  (`JMI_LLM_PROVIDER=gemini`) avoids hosting a model.
