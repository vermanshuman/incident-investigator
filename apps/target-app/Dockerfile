FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY apps/target-app/pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY apps/target-app/app ./app
COPY apps/target-app/faults ./faults
COPY apps/target-app/migrations ./migrations
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
