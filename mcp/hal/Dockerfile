FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8016 \
    MCP_TRANSPORT=http \
    MCP_STATELESS=false

# uv (static binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "fastmcp>=3.4,<4" "httpx"

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py

EXPOSE 8016

ENTRYPOINT ["uv", "run", "/app/mcp_server.py"]
