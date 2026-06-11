FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8012 \
    MCP_TRANSPORT=streamable-http

# uv (static binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "fastmcp>=2.0" "httpx"

WORKDIR /app
COPY server_mcp.py /app/server_mcp.py

EXPOSE 8012

ENTRYPOINT ["uv", "run", "/app/server_mcp.py"]
