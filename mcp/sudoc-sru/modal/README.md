# Sudoc SRU MCP server on Modal

Deploy the server as a serverless HTTPS endpoint on [Modal](https://modal.com).

`mcp_server_stateless.py` is a **standalone duplicate** of the canonical
`../mcp_server.py`, in the shape of
[Modal's own FastMCP example](https://modal.com/docs/examples/mcp_server_stateless):
The whole server is built inside `make_mcp_server()`, runtime imports included.
Modal loads this file on your machine to build the app, and `fastmcp` and `httpx`
are not installed there. It serves the same tools, under the same names, with the
same envelope:

- `search_sudoc`
- `lookup_by_ppn`
- `lookup_by_isbn`
- `count_records`
- `scan_index`

The copy is **hand-kept**, exactly like `../demo/`: change a tool in
`../mcp_server.py` and change it here in the same commit. Nothing enforces it —
`test_tool` below is the check.

## Deploy

```bash
# Once per machine
uvx modal setup

# Ephemeral endpoint, reloads on save — for development
uvx modal serve mcp/sudoc-sru/modal/mcp_server_stateless.py

# Persistent endpoint
uvx modal deploy mcp/sudoc-sru/modal/mcp_server_stateless.py
```

Both print the endpoint. The MCP URL is that URL **with `/mcp/` appended**:

```text
https://<workspace>--smartbiblia-mcp-sudoc-sru-web.modal.run/mcp/
```

## Testing

>Works only with the `modal deploy` command

Open the [MCP inspector](https://github.com/modelcontextprotocol/inspector) and enter the URL of the MCP server that was printed by the modal deploy command, suffixed with /mcp/

```
npx @modelcontextprotocol/inspector
```

## Verify

```bash
uvx modal run mcp/sudoc-sru/modal/mcp_server_stateless.py::test_tool
uvx modal run mcp/sudoc-sru/modal/mcp_server_stateless.py::test_tool \
    --tool-name count_records --arguments '{"query": "mots.titre=bibliotheque"}'
```

The first form lists the tools the deployment actually serves. Compare it with
`uv run ../mcp_server.py --transport stdio`: the two must match, and because this
file is a copy rather than an import, that comparison is the only thing keeping
them in step.

## Connect a client

```json
{
  "mcpServers": {
    "sudoc-sru": {
      "url": "https://<workspace>--smartbiblia-mcp-sudoc-sru-web.modal.run/mcp/"
    }
  }
}
```

## Configuration

This server needs no credential and no endpoint configuration, so
`SECRETS` is empty and there is no Modal Secret to create.

## Why stateless

Modal runs a web endpoint as an autoscaling pool of containers behind one URL,
and it can start, stop or replace a container between two requests. A session
pinned to a replica does not survive that, so the transport is built with
`stateless_http=True` — a new transport per request — which is the same mode as
`../mcp_server.py --transport http --stateless`. A stateless response carries no
`mcp-session-id` header; that is the quickest check of which mode a running
server is in.

The narrowing that comes with it is the documented one: `POST`/`DELETE` only, no
`GET` SSE stream, so no server-initiated messages and no resumability. Every tool
here is a request/response call, so nothing is lost.

`@modal.concurrent(max_inputs=100)` lets one container handle many requests at
once, which is what the pooled `httpx` client built in `make_mcp_server()` is for.

## Cost and exposure

A Modal web endpoint is **public by default** — anyone with the URL can call the
tools, and every call spends your Modal credits and the upstream's rate limit
from an IP the upstream attributes to you.

Containers scale to zero when idle, so an unused deployment costs nothing but
adds a cold start (image pull plus building the FastMCP server) to the first
request after a quiet period.
