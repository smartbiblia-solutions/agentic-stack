FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RDG_BASE_URL=https://entrepot.recherche.data.gouv.fr/api \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8014 \
    MCP_TRANSPORT=streamable-http

# uv (static binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "fastmcp>=2.0" "httpx"

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py

EXPOSE 8014

ENTRYPOINT ["uv", "run", "/app/mcp_server.py"]
