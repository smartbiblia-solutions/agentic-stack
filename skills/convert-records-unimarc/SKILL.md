---
name: convert-records-unimarc
description: >
  Convert UNIMARC bibliographic records between UNIMARC/XML, UNIMARC/JSON,
  and ISO 2709 binary using a local CLI powered by the Python `pymarc` package.
  Use this skill whenever the user asks to transform, normalize, inspect, or
  batch-convert UNIMARC records across XML, JSON, and MARC/ISO formats, including
  commands like "convert UNIMARC XML to JSON", "turn ISO 2709 into XML", or
  "export UNIMARC JSON as binary MARC". Prefer this skill over generic file or
  text-processing skills when the source material is actual UNIMARC record data.
  Returns JSON status summaries plus converted payloads written to stdout or a file,
  depending on the command options.
version: "0.2.0"
author: smartbiblia
maturity: experimental
preferred_output: json
metadata:
  {
    "openclaw": {
      "always": true,
      "requires": { "bins": ["uv"], "env": [], "config": [] }
    }
  }

selection:
  use_when:
    - The task is to convert UNIMARC records between XML, JSON and ISO 2709.
    - A retrieval skill returned raw UNIMARC and the records must be reshaped.
    - The leader length of a UNIMARC/XML file must be validated or repaired.
  avoid_when:
    - The records still have to be retrieved from a catalogue; use search-records-sudoc.
    - The task is generic XML or JSON reshaping with no MARC semantics.
    - The target format is a bibliographic style (BibTeX, CSL) rather than MARC.
  prefer_over:
    - generic-file-conversion
  combine_with:
    - search-records-sudoc

tags:
  - unimarc
  - marc
  - bibliographic
  - conversion
---

# convert-records-unimarc

## Purpose

`scripts/cli.py` is a self-contained CLI intended to run with `uv run`. It wraps
local conversion routines built on top of the Python `pymarc` package and
converts UNIMARC records between three common serializations:

- `xml` — UNIMARC/XML
- `json` — pymarc-style JSON/dictionary structure
- `iso2709` — binary ISO 2709 / MARC exchange format

This skill is for local format conversion, not remote retrieval. It is useful
when an agent must ingest a UNIMARC record in one format, transform it into a
pivot representation, and emit an equivalent record in another format for
storage, downstream processing, or interoperability.

---

## When to use / When not to use

**Use this skill when:**

- The task is to convert UNIMARC records between XML, JSON, and ISO 2709.
- The user needs a local CLI for bibliographic record transformation using pymarc.
- The task involves validating or repairing leader length before XML parsing.

**Do not use this skill when:**

- The task is to retrieve bibliographic records from external catalogs or APIs — use a retrieval skill instead.
- The task is generic XML or JSON reshaping unrelated to MARC/UNIMARC semantics — use general file-processing methods instead.

---

## Subcommands

### `convert` — convert records between formats

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from xml \
  --to json \
  --input ./record.xml \
  --output ./record.json
```

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from json \
  --to iso2709 \
  --input ./record.json \
  --output ./record.mrc
```

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from iso2709 \
  --to xml \
  --input ./record.mrc
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--from` | `xml \| json \| iso2709` | **required** | Source format |
| `--to` | `xml \| json \| iso2709` | **required** | Destination format |
| `--input` | path | **required** | Input file path |
| `--output` | path | stdout | Output path; binary when `--to iso2709` |
| `--pretty` | flag | off | Pretty-print JSON output |
| `--fix-leader` | flag | on | Repair XML leader length before parsing |

### `inspect` — inspect an input file and summarize record counts and format

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py inspect \
  --format xml \
  --input ./records.xml
```

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--format` | `xml \| json \| iso2709` | **required** | Input format |
| `--input` | path | **required** | Input file path |
| `--fix-leader` | flag | on | Repair XML leader length before parsing |

## Output

`inspect` emits strict JSON on stdout. `convert` emits strict JSON on stdout when
`--output` is provided; if `--output` is omitted, the converted payload is sent
to stdout and the JSON status summary is sent to stderr so the payload stream is
not corrupted.

```jsonc
{
  "ok": true,
  "command": "convert",
  "from_format": "xml",
  "to_format": "json",
  "input_path": "./record.xml",
  "output_path": "./record.json",
  "records_in": 1,
  "records_out": 1,
  "bytes_written": 842,
  "warnings": []
}
```

For `inspect`:

```jsonc
{
  "ok": true,
  "command": "inspect",
  "format": "iso2709",
  "input_path": "./records.mrc",
  "records": 12,
  "leaders": ["00000nam0 2200000   4500"],
  "warnings": []
}
```

On error, the CLI emits JSON diagnostics:

```jsonc
{
  "ok": false,
  "error": {
    "type": "ValueError",
    "message": "Unsupported conversion: xml -> csv"
  },
  "warnings": []
}
```

## Composition hints

This skill is a local transformation utility that typically sits after file
acquisition and before downstream metadata analysis.

```text
search-records-sudoc          ← retrieve the records first (UNIMARC/XML)
  → convert-records-unimarc   ← this skill
      ↓
    normalized JSON / XML / ISO 2709 artifact
      ↓
    downstream validation, storage or analysis
```

It performs no network access: give it a file (or a payload written by a
retrieval skill) and it returns another serialization of the same records.

---

## Failure modes

- Exit code is `0` on success.
- Exit code is non-zero on argument or runtime failure.
- Parsing may fail on malformed XML, malformed JSON, invalid ISO 2709 bytes, or
  records that `pymarc` cannot reconstruct.
- XML leaders whose length is not exactly 24 characters can be corrected with
  the built-in leader-fix step before parsing.
- ISO 2709 is binary; avoid printing it directly to an interactive terminal.

## Common workflows

### XML to JSON

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from xml --to json --input ./record.xml --output ./record.json --pretty
```

### JSON to XML

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from json --to xml --input ./record.json --output ./record.xml
```

### ISO 2709 to JSON

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from iso2709 --to json --input ./record.mrc --output ./record.json --pretty
```

### JSON to ISO 2709

```bash
uv run ./skills/convert-records-unimarc/scripts/cli.py convert \
  --from json --to iso2709 --input ./record.json --output ./record.mrc
```

