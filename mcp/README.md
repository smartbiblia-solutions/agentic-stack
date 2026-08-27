# MCP servers

[MCP](https://modelcontextprotocol.io) servers that give AI agents direct access
to scholarly and bibliographic sources. Each one is a single
self-contained `mcp_server.py` with inline
[PEP 723](https://peps.python.org/pep-0723/) dependencies, runnable by
[`uv`](https://docs.astral.sh/uv/) with no install step, shipped with a
`Dockerfile` for VPS deployment and a standalone `demo/` Gradio app that deploys
as a Hugging Face Space.

| Server | Port | Key required | What it exposes |
|---|---|---|---|
| [`openalex`](./openalex/) | 8011 | recommended | ~250M scholarly works: keyword search, DOI resolution, citing works, topic classification |
| [`sudoc-sru`](./sudoc-sru/) | 8012 | no | French union catalogue (SRU/UNIMARC): search, PPN and ISBN lookup, record counts, index scan |
| [`hal`](./hal/) | 8016 | no | HAL, the French national open repository (Solr): scoped search over collections and portals, facets, AuréHAL referentials |
| [`primo`](./primo/) | 8013 | **yes** | An institutional Primo (Ex Libris) discovery layer: catalogue search and record retrieval |
| [`recherche-data-gouv`](./recherche-data-gouv/) | 8014 | no | French national research data repository (Dataverse): dataset and collection search, collection and dataset retrieval, file listings, usage metrics, metadata blocks |
| [`idref-resolver-api`](./idref-resolver-api/) | 8015 | **yes** | Person-to-IdRef-PPN alignment from free-text clues, with an explicit abstention when the evidence is too weak |
| [`theses-fr`](./theses-fr/) | 8017 | no | theses.fr, the French national register of doctoral theses (ABES): thesis search with résumé hydration, record lookup by NNT, person index, facets |
| [`opencitations`](./opencitations/) | 8018 | no | OpenCitations Meta v1 and Index v2 (CC0): citation and reference counts, citing and cited works with self-citation flags, bibliographic metadata by identifier |

[`cli/src/smartbiblia/catalog.toml`](../cli/src/smartbiblia/catalog.toml) is the
inventory of record — it is what `uvx smartbiblia list --kind mcp` reads, and the
table above follows it rather than the other way round.

Each server has its own README with client-by-client setup (Claude Code, Claude
Desktop, Cursor/VS Code), a zero-install stdio recipe, the full flag reference
and troubleshooting.

**Some demo MCP servers are deployed as Hugging Face Spaces, see this [Hugging Face collection](https://huggingface.co/collections/Geraldine/academic-mcp-servers).**

>**Important tip related to demo MCP deployment in Claude Desktop**: Claude Desktop does not natively support direct HTTP/URL-based fields
 (expects local stdio processes using command and args, "http" type or url key are not allowed). 
  To connect Claude Desktop to a streamable HTTP server or a remote url, you must wrap the url using a standard stdio command via npx mcp-remote in your configuration file.
  ```json
	  {
	  "mcpServers": {
		"my-remote-server": {
		  "command": "npx",
		  "args": [
			"mcp-remote",
			"http://127.0.0.1:8080/mcp"
		  ]
		}
	  }
	}
  ```
---

## Tools at a glance

**`openalex`** — `search_works`, `search_semantic`, `lookup_by_doi`,
`get_citing_works`, `classify_text`

**`sudoc-sru`** — `search_sudoc`, `lookup_by_ppn`, `lookup_by_isbn`,
`count_records`, `scan_index`

**`hal`** — `search_hal`, `list_portals`, `lookup_reference`

**`primo`** — `search_catalog`, `get_record`

**`recherche-data-gouv`** — `search`, `metrics`, `metadatablocks`, `get_collection`, `list_collection_contents`, `get_dataset`, `list_dataset_files`

**`idref-resolver-api`** — `align_person`

**`theses-fr`** — `search_theses`, `get_thesis`, `search_persons`,
`list_facets`, `search_by_organisme`

**`opencitations`** — `get_citation_counts`, `get_citations`,
`get_references`, `lookup_metadata`, `list_works_by_person`

---

## Quick start

### One server, no install

```bash
uv run mcp/openalex/mcp_server.py --transport stdio
```

Or straight from GitHub, without cloning:

```bash
claude mcp add openalex -- \
  uv run https://raw.githubusercontent.com/smartbiblia-solutions/agentic-stack/main/mcp/openalex/mcp_server.py \
  --transport stdio
```

### All servers, via Docker

```bash
cp mcp/.env.example mcp/.env    # fill in OPENALEX_API_KEY, the PRIMO_* and IDREF_* values
docker compose -f mcp/compose.yml up --build
```

Endpoints: `http://localhost:{8011,8012,8013,8014,8015,8016,8017,8018}/mcp`.

### In a browser

Every server folder also holds a `demo/` — a **standalone** Gradio app that
re-implements **every** tool of its `mcp_server.py` against the same API and
wraps them in a UI:

```bash
cd mcp/openalex/demo
uv run --with 'gradio[mcp]>=6,<7' --with httpx app.py
```

`demo/app.py` imports nothing from the folder above it: the Space root is
`demo/`, so `mcp_server.py` does not exist there. Its tools are a hand-kept copy
— **same tools, same names, same response shape**; what a demo may narrow is a
tool's *surface*, and only where a browser form justifies it: tighter result caps
than canonical, and the odd argument no form can express. Every narrowing is
stated in the tool docstring and in `demo/README.md`. Change one, change the
other.

Each `demo/` is a deployable Hugging Face Space as it stands (`git subtree push
--prefix=mcp/<server>/demo space main`); see the folder's README. The demo MCP
endpoint it serves at `/gradio_api/mcp/sse` is **secondary** — `mcp_server.py`
remains canonical, with the untightened result limits and the full argument
surface.

### Via the CLI

The [`smartbiblia`](../cli/) CLI downloads a server from this catalogue and
prints the client configuration block for it:

```bash
uvx smartbiblia list --kind mcp             # browse
uvx smartbiblia info primo                  # port, entrypoint, required env vars
uvx smartbiblia add openalex --kind mcp     # → ./mcp/openalex/
uvx smartbiblia mcp-config openalex         # mcpServers block to paste into a client
```

`mcp-config` takes `--transport http` for an HTTP block, or `--remote` to run the
server straight from GitHub with nothing installed. It never writes a key: the
expected variables are pre-filled empty. Full reference in
[`../cli/README.md`](../cli/README.md).

---

## Conventions

The repository-wide rules — pooled `httpx` client, errors as data, the common
record schema, secrets — are in the [root README](../README.md#conventions) and
hold here too. What follows is specific to the MCP servers:

- **One file**: `mcp_server.py`, plus a `Dockerfile`, a `README.md`, and a
  `demo/` folder (`app.py`, `requirements.txt`, `README.md` with the Space
  front-matter) deployable as a Hugging Face Space. `demo/app.py` is a separate
  artefact: it re-implements **every** tool of the server — possibly with
  narrower arguments and tighter result caps — and imports nothing from its
  parent folder, which does not exist once `demo/` is the Space root.
- **FastMCP is pinned to `>=3.4,<4`** in the PEP 723 header and in every
  `Dockerfile`, so `uv run` resolves the same major everywhere. FastMCP 4 is
  still a beta prerelease; `uv` skips prereleases by default, so moving to it
  would mean `--prerelease=allow` on every zero-install command.
- **Transport is a flag**: `--transport stdio | http | sse` (default `http`;
  `streamable-http` is accepted as an alias of `http`), with `--host` and
  `--port`. All three also read `MCP_TRANSPORT` / `MCP_HOST` / `MCP_PORT` so
  containers can be configured without changing the entrypoint.
- **`--stateless` for sessionless HTTP**: builds a new transport per request so
  no session is pinned to a replica — what a load-balanced or multi-worker
  deployment needs. Off by default (a single long-lived process is cheaper
  stateful), also readable from `MCP_STATELESS`, and rejected with `sse`, which
  cannot be stateless.
- **Retry and backoff are flags, not env vars**: `--http-timeout`,
  `--max-retries`, `--backoff-base`, `--backoff-factor`, `--jitter-max`. Only
  endpoints and credentials come from the environment. (Skills apply the same
  rule with constants instead of flags.)
- **Tools return structured dicts**, with a `source`, a `command`, an `error`
  field, and an optional `trace` array when `--trace` is on.

---

## Companion skills

Several servers have a skill counterpart under [`../skills/`](../skills/) — the
same source, exposed as a CLI for agents that prefer a shell tool over an MCP
connection:

| Server | Skill |
|---|---|
| `openalex` | [`search-works-openalex`](../skills/search-works-openalex/SKILL.md) |
| `sudoc-sru` | [`search-records-sudoc`](../skills/search-records-sudoc/SKILL.md) |
| `hal` | [`search-records-hal`](../skills/search-records-hal/SKILL.md) |
| `idref-resolver-api` | [`resolve-persons-idref`](../skills/resolve-persons-idref/SKILL.md) |
| `theses-fr` | [`search-theses-fr`](../skills/search-theses-fr/SKILL.md) |
| `opencitations` | [`lookup-citations-opencitations`](../skills/lookup-citations-opencitations/SKILL.md) |

---

## See also

- Repo overview and shared conventions: [`../README.md`](../README.md)
- `smartbiblia` command reference: [`../cli/README.md`](../cli/README.md)
- MCP protocol: <https://modelcontextprotocol.io>
- FastMCP: <https://gofastmcp.com>
