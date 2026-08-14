# Primo MCP server on Modal

Deploy the server as a serverless HTTPS endpoint on [Modal](https://modal.com).

`mcp_server_stateless.py` is a **standalone duplicate** of the canonical
`../mcp_server.py`, in the shape of
[Modal's own FastMCP example](https://modal.com/docs/examples/mcp_server_stateless):
it mounts nothing into the image and imports nothing from the parent folder. The
whole server is built inside `make_mcp_server()`, runtime imports included —
Modal loads this file on your machine to build the app, and `fastmcp` and `httpx`
are not installed there. It serves the same tools, under the same names, with the
same envelope:

- `search_catalog`
- `get_record`

The copy is **hand-kept**, exactly like `../demo/`: change a tool in
`../mcp_server.py` and change it here in the same commit. Nothing enforces it —
`test_tool` below is the check.

## Deploy

```bash
# Once per machine
uvx modal setup

# Ephemeral endpoint, reloads on save — for development
uvx modal serve mcp/primo/modal/mcp_server_stateless.py

# Persistent endpoint
uvx modal deploy mcp/primo/modal/mcp_server_stateless.py
```

Both print the endpoint. The MCP URL is that URL **with `/mcp/` appended**:

```text
https://<workspace>--smartbiblia-mcp-primo-web.modal.run/mcp/
```

## Testing

>Works only with the `modal deploy` command

Open the [MCP inspector](https://github.com/modelcontextprotocol/inspector) and enter the URL of the MCP server that was printed by the modal deploy command, suffixed with /mcp/

```
npx @modelcontextprotocol/inspector
```

## Verify

```bash
uvx modal run mcp/primo/modal/mcp_server_stateless.py::test_tool
uvx modal run mcp/primo/modal/mcp_server_stateless.py::test_tool \
    --tool-name search_catalog --arguments '{"query": "any,contains,climate", "max_results": 3}'
```

The first form lists the tools the deployment actually serves. Compare it with
`uv run ../mcp_server.py --transport stdio`: the two must match, and because this
file is a copy rather than an import, that comparison is the only thing keeping
them in step.

## Connect a client

```json
{
  "mcpServers": {
    "primo": {
      "url": "https://<workspace>--smartbiblia-mcp-primo-web.modal.run/mcp/"
    }
  }
}
```

## Configuration

The server reads its configuration from the environment, and a Modal Secret is
how that environment is populated:

```bash
modal secret create smartbiblia-primo PRIMO_API_KEY=... PRIMO_VID=... PRIMO_TAB=... PRIMO_SCOPE=...
```

| Variable | Required | Meaning |
|---|---|---|
| `PRIMO_API_KEY` | yes | Ex Libris API key. Institution- and environment-scoped. |
| `PRIMO_VID` | yes | View id, e.g. `INST:VIEW`. |
| `PRIMO_TAB` | yes | Search tab configured in the Primo Back Office. |
| `PRIMO_SCOPE` | yes | Search scope configured in the Primo Back Office. |
| `PRIMO_REGION` | no | `na` | `eu` | `ap` | `ca` | `cn`. Default `na`. |
| `PRIMO_INST` | no | Institution code, when the view needs one. |
| `PRIMO_LANG` | no | Interface language. Default `en`. |

`mcp_server_stateless.py` already declares this Secret with `required_keys`, so
`modal deploy` fails with the missing key named rather than deploying a server
that breaks on its first request.

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

A Primo key is billed to one institution: keep this deployment private, or put
an authenticating proxy in front of it. Modal web endpoints are public by
default.
