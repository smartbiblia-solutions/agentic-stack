FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRIMO_API_KEY= \
    PRIMO_REGION=na \
    PRIMO_VID= \
    PRIMO_TAB= \
    PRIMO_SCOPE= \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8013 \
    MCP_TRANSPORT=streamable-http

# uv (static binary)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache "fastmcp>=2.0" "httpx"

WORKDIR /app
COPY mcp_server.py /app/mcp_server.py

EXPOSE 8013

ENTRYPOINT ["uv", "run", "/app/mcp_server.py"]
