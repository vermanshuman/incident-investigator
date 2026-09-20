FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
COPY packages/mcp-server/pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY packages/mcp-server/mcp_server ./mcp_server
CMD ["uv", "run", "python", "-m", "mcp_server.server"]
