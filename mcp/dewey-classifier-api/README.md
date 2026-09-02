# Dewey Classifier MCP Server

An [MCP](https://modelcontextprotocol.io) server that gives AI agents access to a
deployed **humatheque-dewey-classifier-api** service: given the metadata of a
**French doctoral thesis** — its title, its subject keywords, its abstract — it
returns the **Dewey classes** that text most resembles, ranked by semantic
similarity, so an indexing decision starts from a shortlist instead of a blank
field.

The vocabulary is the reduced Dewey list French thesis cataloguing uses in the
**Sudoc**: 98 classes, the main divisions and their tens plus the finer entries
that rule keeps (`004`, `020`, `060`, `070`, `090`, `796`, `944`). It is not the
full Dewey schedules, and it is why the answer stops at the division level — that
is the granularity a thesis record carries. Any text is accepted and any text
gets an answer, but a document that is not a thesis is being ranked against a
list built for theses; report it as a coarse discipline hint, not as an indice.

See the
[`humatheque-dewey-classifier-api` repo](https://github.com/gegedenice/humatheque-dewey-classifier-api)
for self-hosted deployment of the API. A public deployment runs at
<https://dewey-classifier.smartbiblia.fr> and is the default endpoint here.

## Tools

| Tool | Purpose |
|---|---|
| `classify_text` | Rank Dewey classes against one or several theses. Returns one entry per text, each with its ranked classes, their French labels and their similarity scores. |
| `list_dewey_classes` | List every class the deployment can actually assign — the Sudoc thesis list as the operator's own taxonomy file holds it, not the full Dewey schedules. |

**The scores are a ranking, not a confidence.** They are cosine similarities;
with e5-style models they cluster high (~0.7–0.9) even for weak matches, so the
signal is the order and the gap between rank 1 and rank 2, never the absolute
value. `local` and `albert` scores are on different scales and must never be
compared. And the list is coarse on purpose — it is the thesis-cataloguing one —
so the answer is a division-level indice, not a call number.

The server is a single self-contained file, `mcp_server.py`, with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies (`fastmcp`, `httpx`)
that [`uv`](https://docs.astral.sh/uv/) installs automatically on first run.

---

## Example prompts

Once the server is connected, these are the kinds of request it answers:

- *"À quelle classe Dewey correspond la thèse « Histoire politique de Buenos Aires au XIXe siècle » ?"* → `classify_text`
- *"Voici 30 sujets de thèses déposées, propose un indice pour chacun."* → `classify_text` in batches of at most 50 texts
- *"Classe ce résumé, mais seulement parmi 930, 940 et 944."* → `classify_text` with `codes`
- *"Quelles classes ce classifieur connaît-il ? Peut-il descendre sous 940 ?"* → `list_dewey_classes` (no: the thesis list stops at the division)
- *"Donne-moi un seul indice, le meilleur."* → `classify_text` with `classification_type: "single-label"`
- *"Compare le classement local et le rerank Albert sur ce titre."* → two `classify_text` calls, comparing the **orders**, not the scores

**Read the ranking, not the number.** A wrong class routinely scores 0.79 where
the right one scores 0.82. Report the top candidates and let a cataloguer decide.

---

## Prerequisites

**`uv`** (handles Python + dependencies automatically):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**A reachable classifier.** The public deployment is the default, so nothing has
to be set to get started. Point the server at your own — and keep the texts in
house — with:

```bash
export DEWEY_API_URL=https://dewey.example.org
export DEWEY_API_KEY=…          # sent as X-API-Key; never a tool argument
```

`DEWEY_API_KEY` is read from the environment only. It is never accepted as a tool
argument, never logged, and never echoed into a payload or a trace event. The
public deployment currently runs without a key.

---

## Option 1 — Local install

### 1. Clone and run

```bash
git clone --filter=blob:none --sparse https://github.com/smartbiblia-solutions/agentic-stack.git mcp
cd mcp
git sparse-checkout set mcp/dewey-classifier-api
```

Start the server with the transport of your choice:

```bash
# stdio — the client launches and manages the process
uv run mcp/dewey-classifier-api/mcp_server.py --transport stdio

# sse — persistent server, SSE endpoint
uv run mcp/dewey-classifier-api/mcp_server.py \
  --host 0.0.0.0 --port 8019 --transport sse
# → endpoint: http://localhost:8019/sse

# http — persistent server, HTTP endpoint (recommended for HTTP mode)
uv run mcp/dewey-classifier-api/mcp_server.py \
  --host 0.0.0.0 --port 8019 --transport http
# → endpoint: http://localhost:8019/mcp

# Add --stateless to serve HTTP without sessions: a new transport per
# request, so nothing is pinned to a replica. Needed behind a load
# balancer or with several uvicorn workers; rejected with --transport sse.
```

### 1.1 Claude Code

```bash
# stdio (no persistent server needed — Claude Code manages the process)
claude mcp add dewey-classifier-api \
  --env DEWEY_API_URL=https://dewey-classifier.smartbiblia.fr -- \
  uv run /ABS/PATH/mcp/dewey-classifier-api/mcp_server.py --transport stdio

# sse (start the server first with --transport sse)
claude mcp add --transport sse dewey-classifier-api http://localhost:8019/sse

# streamable-http (start the server first with --transport http)
claude mcp add --transport http dewey-classifier-api http://localhost:8019/mcp
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 1.2 Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%AppData%\Claude\claude_desktop_config.json` (Windows).

**stdio** (Claude Desktop launches the process — no server to start):

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "command": "uv",
      "args": [
        "run",
        "/ABS/PATH/mcp/dewey-classifier-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "DEWEY_API_URL": "https://dewey-classifier.smartbiblia.fr",
        "DEWEY_API_KEY": ""
      }
    }
  }
}
```

**http** (start the server first, then point Claude Desktop at it):

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "url": "http://localhost:8019/mcp"
    }
  }
}
```

On Windows, use escaped backslashes in the path:
`"C:\\ABS\\PATH\\mcp\\dewey-classifier-api\\mcp_server.py"`.
Restart Claude Desktop after saving; tools appear under the plug icon.

### 1.3 Cursor / VS Code / other `mcp.json` clients

**stdio** (Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`):

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "command": "uv",
      "args": [
        "run", "/ABS/PATH/mcp/dewey-classifier-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "DEWEY_API_URL": "https://dewey-classifier.smartbiblia.fr"
      }
    }
  }
}
```

**http** (start the server first):

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "url": "http://localhost:8019/mcp"
    }
  }
}
```

### 1.4 Docker

```bash
docker build -t mcp-dewey-classifier-api ./mcp/dewey-classifier-api
docker run -p 8019:8019 \
  -e DEWEY_API_URL=https://dewey-classifier.smartbiblia.fr \
  mcp-dewey-classifier-api

# Or start every MCP server at once
cp mcp/.env.example mcp/.env   # fill in DEWEY_API_URL, DEWEY_API_KEY, …
docker compose -f mcp/compose.yml up --build
```

---

## Option 2 — Zero-install (stdio only)

`uv` can run a script directly from a URL — no clone, no local files.
This works as a true single-step zero-install **only with `stdio`**: the client
config embeds the `uv run <url>` command and the client manages the process itself.

For `sse` or `http`, `uv run <url>` still starts a local server on
localhost — you would then need to register the endpoint separately, which is
equivalent to Option 1 HTTP mode (just without cloning first).

### 2.1 Claude Code

```bash
claude mcp add dewey-classifier-api \
  --env DEWEY_API_URL=https://dewey-classifier.smartbiblia.fr -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/dewey-classifier-api/mcp_server.py \
  --transport stdio
```

Check status: `claude mcp list` or `/mcp` inside a session.

### 2.2 Claude Desktop

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/dewey-classifier-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "DEWEY_API_URL": "https://dewey-classifier.smartbiblia.fr"
      }
    }
  }
}
```

Restart Claude Desktop after saving; tools appear under the plug icon.

### 2.3 Cursor / VS Code / other `mcp.json` clients

(Cursor: `~/.cursor/mcp.json` — VS Code: `.vscode/mcp.json`)

```jsonc
{
  "mcpServers": {
    "dewey-classifier-api": {
      "command": "uv",
      "args": [
        "run",
        "https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/dewey-classifier-api/mcp_server.py",
        "--transport", "stdio"
      ],
      "env": {
        "DEWEY_API_URL": "https://dewey-classifier.smartbiblia.fr"
      }
    }
  }
}
```

---

## Configuration

| Flag | Default | Notes |
|---|---|---|
| `--api-url` | `https://dewey-classifier.smartbiblia.fr` | Classifier base URL. Also reads `DEWEY_API_URL`. |
| `--host` | `0.0.0.0` | Bind host (HTTP/SSE modes). |
| `--port` | `8019` | Bind port (HTTP/SSE modes). |
| `--transport` | `http` | `stdio` \| `http` \| `sse`. `streamable-http` is accepted as an alias of `http`. Also reads `MCP_TRANSPORT`. |
| `--stateless` | off | Stateless HTTP: a new transport per request, so no session is pinned to a replica — required behind a load balancer or with several uvicorn workers. Rejected with `sse`. Also reads `MCP_STATELESS`. |
| `--http-timeout` | `120.0` | Request timeout in seconds. The first call against a cold classifier loads its embedding model and builds the taxonomy index; do not lower this. |
| `--max-retries` | `2` | Retry attempts on transient errors (429, 5xx). |
| `--backoff-base` | `1.0` | Exponential backoff base in seconds. |
| `--backoff-factor` | `2.0` | Backoff multiplier. |
| `--jitter-max` | `0.25` | Max random jitter per retry in seconds. |
| `--trace` | off | Include the API round trips in every tool response. No secret is ever traced. |

The credential has no flag: it is read from `DEWEY_API_KEY` only, so it never
lands in a process listing or a client config's `args`. See
`uv run mcp_server.py --help` for the full reference.

---

## Verify

```bash
# HTTP/SSE mode: check the endpoint is live (a 307/406 is normal without a handshake)
curl -i http://localhost:8019/mcp    # http
curl -i http://localhost:8019/sse    # sse

# The classifier itself
curl -s https://dewey-classifier.smartbiblia.fr/health

# stdio mode: check via the client's MCP panel
# In Claude Code: /mcp
```

---

## Troubleshooting

- **`error: cannot reach the API`** — `DEWEY_API_URL` points nowhere, or the
  service is down. The tool still returns HTTP 200 with the failure as data.
- **`API 401`** — `DEWEY_API_KEY` is missing or refused by that deployment.
- **`API 400: No known Dewey codes provided.`** — every code in `codes` is
  outside the thesis list. Unknown codes are dropped silently, but a list with
  none known is a hard error: call `list_dewey_classes` to see what exists. A
  code can be perfectly valid in Dewey and still be absent here.
- **`API 400` naming a method** — only `local` and `albert` exist, and `albert`
  needs the deployment to hold an Albert key. `local` always works.
- **The first call takes 30–60 s** — expected on a cold deployment: the service
  downloads its embedding model and builds the taxonomy index, then answers in
  well under a second. Do not lower `--http-timeout` to "fix" it.
- **Every score looks high** — that is the model, not a bug. Cosine similarities
  with e5 cluster in 0.7–0.9. Use the ranking and the gap, not the value.
- **The class you want does not exist** — the thesis list holds no `005.13`, by
  design. If your practice needs one, it is the operator's file: edit
  `taxonomy.json` on the API side and restart it.
- **First run is slow** — `uv` is resolving and caching dependencies; subsequent
  runs start in under a second.

---

## Browser demo / Hugging Face Space

[`demo/`](demo/) holds a **standalone** Gradio app that re-implements **every**
tool of `mcp_server.py` — `classify_text` and `list_dewey_classes` — against the
same upstream and wraps them in a browser UI. Same names, same response shape;
only the argument surface and the result caps may be narrower, and each narrowing
is stated in the tool docstring and in [`demo/README.md`](./demo/README.md).
Change one, change the other.

```bash
cd demo
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
# http://localhost:7860
```

Launched with `mcp_server=True`, it also serves its tools at `/gradio_api/mcp/`.
That endpoint is **demo-grade and secondary** — the canonical MCP endpoint is
`mcp_server.py`, with the untightened result limits and the full argument
surface. Set `GRADIO_MCP_SERVER=false` wherever the real server is already
reachable, so clients cannot bind to the wrong one.

Check what it exposes:

```bash
curl -s localhost:7860/gradio_api/mcp/schema | python3 -m json.tool
```

`demo/` is a deployable Space as it stands — `demo/README.md` carries the YAML
configuration block, and `demo/requirements.txt` is what the Space installs:

```bash
git remote add space https://huggingface.co/spaces/<owner>/<space-name>
git subtree push --prefix=mcp/dewey-classifier-api/demo space main
```

> Every classification runs an embedding pass upstream, so a public Space spends
> the classifier's capacity on every visitor's click. Put `DEWEY_API_URL` and any
> `DEWEY_API_KEY` in the Space settings — never in this repository.

---

## Serverless deployment

[`modal/`](modal/) holds a **standalone duplicate** of this server for
[Modal](https://modal.com): an autoscaling HTTPS endpoint with no container to
run, serving the same two tools statelessly. See
[`modal/README.md`](./modal/README.md).

```bash
uvx modal deploy mcp/dewey-classifier-api/modal/mcp_server_stateless.py
```

---

## See also

- The API: <https://github.com/gegedenice/humatheque-dewey-classifier-api> ·
  live at <https://dewey-classifier.smartbiblia.fr> ·
  Swagger at <https://dewey-classifier.smartbiblia.fr/docs>
- Companion agent skill: [`classify-theses-dewey`](../../skills/classify-theses-dewey/)
  (same service, CLI shape), whose
  [`references/llm.md`](../../skills/classify-theses-dewey/references/llm.md)
  carries the taxonomy snapshot and the API's quirks.
- MCP protocol: <https://modelcontextprotocol.io>
