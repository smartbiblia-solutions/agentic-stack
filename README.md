# Agentic Stack

Reusable skills and MCP servers for AI agents working on libraries, scholarly information, and research workflows.

---

## Skills: llm.md

Some skills in this repository wrap APIs or services that do not provide a public llm.txt file:
to make these skills easier to understand, maintain, and extend, I sometimes include a local documentation snapshot at

`skills/<skill-name>/references/llm.md`

These files contain content derived from an API documentation or other relevant technical references, and serve as a structured, agent-friendly knowledge source for the skill 
that can be viewed as a ready-to-publish llm.txt equivalent bundled with the project.


## Skills: Environment Variables

Some skills include a `scripts/` directory containing:

```text
scripts/
├── cli.py
└── .env.example
```

The `.env.example` file provides a convenient way to customize the behavior of the skill, but creating a `.env` file is usually **optional**.

Most configuration values are loaded through environment variables with sensible built-in defaults defined directly in `cli.py`, for example:

```python
HTTP_TIMEOUT = _env_float("OPENALEX_HTTP_TIMEOUT", 15.0)
MAX_RETRIES = max(1, _env_int("OPENALEX_MAX_RETRIES", 2))
BACKOFF_BASE = max(0.0, _env_float("OPENALEX_BACKOFF_BASE", 1.0))
BACKOFF_FACTOR = max(1.0, _env_float("OPENALEX_BACKOFF_FACTOR", 2.0))
JITTER_MAX = max(0.0, _env_float("OPENALEX_JITTER_MAX", 0.25))
TRACE_DEFAULT = os.getenv("OPENALEX_TRACE", "0").strip() in ("1", "true", "True", "yes", "YES")
```

As a result, most skills can be used immediately without any additional configuration.

If you need to customize the behavior:

1. Copy `.env.example` to `.env`
2. Adjust the values to your needs
3. Run the skill normally

Alternatively, advanced users can modify the default values directly in `cli.py`.

Unless a skill requires API credentials, the provided defaults should be sufficient for most use cases.