FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY packages/agent /packages/agent
COPY apps/worker/pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY apps/worker/worker ./worker
CMD ["uv", "run", "python", "-m", "worker.main"]
