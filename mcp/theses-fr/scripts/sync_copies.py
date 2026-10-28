#!/usr/bin/env python3
"""Regenerate the two copies of ../mcp_server.py that cannot import it.

- modal/mcp_server_stateless.py: nothing is mounted into the Modal image, so
  the server's code lives inside make_mcp_server(). Its body is rewritten here
  — argparse layer replaced by its defaults, module globals turned into
  closure variables — and the Modal wrapper (`web`, `test_tool`) is untouched.
- demo/theses_core.py: the Hugging Face Space is pushed from demo/ alone, so
  the Gradio app imports this generated module instead of the server: the same
  helpers and tool functions, without FastMCP and its decorators.

Run it after every change to mcp_server.py, and commit the three files together.

  python3 mcp/theses-fr/scripts/sync_copies.py
"""
import pathlib
import re
import textwrap

root = pathlib.Path(__file__).resolve().parent.parent
src = (root / "mcp_server.py").read_text()

body = src[src.index('API_URL = "https://theses.fr/api/v1"'):src.index('\nif __name__ == "__main__":')]
# Drop the argparse layer and the derived constants.
consts = '''HTTP_TIMEOUT = 20.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_FACTOR = 2.0
JITTER_MAX = 0.25
TRACE = False
# The --etablissements flag of the canonical server, as an environment variable.
ETAB_SOURCE = os.environ.get("THESES_FR_ETABLISSEMENTS")

'''
body = body[:body.index("def _parse_args()")] + consts + body[body.index("mcp = FastMCP("):]
body = body.replace("args.etablissements", "ETAB_SOURCE")
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
'''


def write_modal() -> None:
    path = root / "modal/mcp_server_stateless.py"
    modal = path.read_text()
    inner_body = body.replace("    global _ETAB", "    nonlocal _ETAB")
    inner = textwrap.indent(imports + "from fastmcp import FastMCP\n\n" + inner_body.rstrip()
                            + "\n\nreturn mcp\n", "    ")
    inner = re.sub(r"^\s+$", "", inner, flags=re.M)
    start = modal.index("    import asyncio\n", modal.index("def make_mcp_server():"))
    end = modal.index("\n\n@app.function(secrets=SECRETS)\n@modal.concurrent")
    path.write_text(modal[:start] + inner.rstrip() + "\n" + modal[end:])


def write_demo_core() -> None:
    core = body
    # The FastMCP instance (its `instructions` included) and the decorators go:
    # the Gradio app registers the tools itself.
    a = core.index("mcp = FastMCP(")
    b = core.index("\n)\n", a) + len("\n)\n")
    core = core[:a] + core[b:].lstrip("\n")
    core = core.replace("@mcp.tool\n", "")
    header = '''"""theses.fr core for the Gradio demo — GENERATED, do not edit.

Generated from ../mcp_server.py by ../scripts/sync_copies.py: the canonical
server's helpers and tool functions, without FastMCP. The Hugging Face Space is
pushed from demo/ alone, so app.py cannot import the server itself.
"""

from __future__ import annotations

'''
    (root / "demo/theses_core.py").write_text(header + imports + "\n\n" + core.rstrip() + "\n")


write_modal()
write_demo_core()
