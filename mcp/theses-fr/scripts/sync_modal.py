#!/usr/bin/env python3
"""Regenerate the body of modal/mcp_server_stateless.py from ../mcp_server.py.

The Modal copy cannot import the canonical server (nothing is mounted into its
image), so it carries the same code inside make_mcp_server(). This rewrites
that body from the canonical file — argparse layer replaced by its defaults,
module globals turned into closure variables — and leaves the Modal wrapper
(`web`, `test_tool`) untouched. Run it after every change to mcp_server.py.

  python3 mcp/theses-fr/scripts/sync_modal.py
"""
import pathlib
import re
import textwrap

root = pathlib.Path(__file__).resolve().parent.parent
src = (root / "mcp_server.py").read_text()
modal = (root / "modal/mcp_server_stateless.py").read_text()

body = src[src.index('API_URL = "https://theses.fr/api/v1"'):src.index('\nif __name__ == "__main__":')]
# Drop the argparse layer and the derived constants.
a = body.index("def _parse_args()")
b = body.index("mcp = FastMCP(")
consts = '''HTTP_TIMEOUT = 20.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
TRACE = False
# The --etablissements flag of the canonical server, as an environment variable.
ETAB_SOURCE = os.environ.get("THESES_FR_ETABLISSEMENTS")

'''
body = body[:a] + consts + body[b:]
body = body.replace("args.etablissements", "ETAB_SOURCE")
body = body.replace("    global _ETAB", "    nonlocal _ETAB")
imports = '''import asyncio
import json
import os
import pathlib
import random
import re
import time
import unicodedata
import urllib.parse
from typing import Any, Literal

import httpx
from fastmcp import FastMCP

'''
inner = textwrap.indent(imports + body.rstrip() + "\n\nreturn mcp\n", "    ")
inner = re.sub(r"^\s+$", "", inner, flags=re.M)
start = modal.index('    import asyncio\n', modal.index("def make_mcp_server():"))
end = modal.index("\n\n@app.function(secrets=SECRETS)\n@modal.concurrent")
modal = modal[:start] + inner.rstrip() + "\n" + modal[end:]
modal = modal.replace("Tools served: `search_theses`, `get_thesis`, `search_persons`, `list_facets`, `search_by_organisme`.",
                      "Tools served: `search_theses`, `resolve_establishment`, `get_thesis`, `search_persons`,\n`list_facets`, `search_by_organisme`.")
(root / "modal/mcp_server_stateless.py").write_text(modal)
