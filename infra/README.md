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

Flows + deployments live in `../orchestration` (`prefect.yaml`). Deploy them to
your centralized Prefect server's `jmi-pool` work pool:

```bash
cd orchestration && prefect deploy --all
```

The worker container (or an EC2 worker) runs `prefect worker start --pool jmi-pool`.

## AWS notes (improvement section)

- Worker on a small EC2 (or ECS Fargate task) using `worker.Dockerfile`.
- Secrets via SSM Parameter Store / Secrets Manager → injected as env vars.
- The app deploys free to Streamlit Community Cloud, or as an ECS service.
- Ollama needs RAM/GPU; for a server deployment, Gemini free tier
  (`JMI_LLM_PROVIDER=gemini`) avoids hosting a model.
