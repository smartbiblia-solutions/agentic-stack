#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "pymarc>=5.2.0",
# ]
# ///

import argparse
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from pymarc import MARCReader, parse_json_to_array, parse_xml_to_array, record_to_xml


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    raise SystemExit(exit_code)


def emit_payload_to_stdout(payload, fmt: str) -> int:
    if fmt == "iso2709":
        sys.stdout.buffer.write(payload)
        return len(payload)
    sys.stdout.write(payload)
    if not str(payload).endswith("\n"):
        sys.stdout.write("\n")
    return len(payload.encode("utf-8"))


def emit_json_to_stderr(obj: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def fix_leader_length(xml_record: str) -> str:
    match = re.search(r"<leader>(.*?)</leader>", xml_record, re.DOTALL)
    if not match:
        return xml_record

    original = match.group(1)
    expected = 24
    current = len(original)
    if current == expected:
        return xml_record

    if current < expected:
        corrected = original.ljust(expected, " ")
    else:
        corrected = original[:expected]

    return re.sub(
        r"<leader>.*?</leader>",
        f"<leader>{corrected}</leader>",
        xml_record,
        count=1,
        flags=re.DOTALL,
    )


class UnimarcConverter:
    @staticmethod
    def xml_to_records(xml_string: str, fix_leader: bool = True):
        payload = fix_leader_length(xml_string) if fix_leader else xml_string
        xml_file = BytesIO(payload.encode("utf-8"))
        return parse_xml_to_array(xml_file)

    @staticmethod
    def json_to_records(json_string: str):
        return parse_json_to_array(json_string)

    @staticmethod
    def iso_to_records(iso_bytes: bytes):
        return list(MARCReader(BytesIO(iso_bytes), to_unicode=True, force_utf8=True))

    @staticmethod
    def records_to_json(records: list[Any]) -> str:
        return json.dumps([record.as_dict() for record in records], ensure_ascii=False)

    @staticmethod
    def records_to_xml(records: list[Any]) -> str:
        return "\n".join(record_to_xml(record).decode("utf-8") for record in records)

    @staticmethod
    def records_to_iso(records: list[Any]) -> bytes:
        return b"".join(record.as_marc() for record in records)


def read_input(path: Path, fmt: str):
    if fmt == "iso2709":
        return path.read_bytes()
    return path.read_text(encoding="utf-8")


def parse_records(payload, fmt: str, fix_leader: bool = True):
    if fmt == "xml":
        return UnimarcConverter.xml_to_records(payload, fix_leader=fix_leader)
    if fmt == "json":
        records = UnimarcConverter.json_to_records(payload)
        if isinstance(records, list):
            return records
        return [records]
    if fmt == "iso2709":
        return UnimarcConverter.iso_to_records(payload)
    raise ValueError(f"Unsupported format: {fmt}")


def serialize_records(records, fmt: str, pretty: bool = False):
    if fmt == "json":
        data = [record.as_dict() for record in records]
        return json.dumps(data, ensure_ascii=False, indent=2 if pretty else None)
    if fmt == "xml":
        return UnimarcConverter.records_to_xml(records)
    if fmt == "iso2709":
        return UnimarcConverter.records_to_iso(records)
    raise ValueError(f"Unsupported format: {fmt}")


def write_output(payload, path: Path | None, fmt: str) -> int:
    if path is None:
        return emit_payload_to_stdout(payload, fmt)

    if fmt == "iso2709":
        path.write_bytes(payload)
        return len(payload)

    text = payload if isinstance(payload, str) else payload.decode("utf-8")
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def cmd_convert(args):
    warnings = []
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else None

    payload = read_input(input_path, args.from_format)
    records = parse_records(payload, args.from_format, fix_leader=args.fix_leader)
    rendered = serialize_records(records, args.to_format, pretty=args.pretty)
    bytes_written = write_output(rendered, output_path, args.to_format)

    result = {
        "ok": True,
        "command": "convert",
        "from_format": args.from_format,
        "to_format": args.to_format,
        "input_path": str(input_path),
        "output_path": str(output_path) if output_path else None,
        "records_in": len(records),
        "records_out": len(records),
        "bytes_written": bytes_written,
        "warnings": warnings,
    }
    if output_path is None:
        emit_json_to_stderr(result)
        raise SystemExit(0)
    emit(result)


def cmd_inspect(args):
    warnings = []
    input_path = Path(args.input)
    payload = read_input(input_path, args.format)
    records = parse_records(payload, args.format, fix_leader=args.fix_leader)
    leaders = []
    for record in records[:10]:
        leader = getattr(record, "leader", None)
        if leader is not None:
            leaders.append(str(leader))

    emit({
        "ok": True,
        "command": "inspect",
        "format": args.format,
        "input_path": str(input_path),
        "records": len(records),
        "leaders": leaders,
        "warnings": warnings,
    })


def build_parser():
    parser = argparse.ArgumentParser(description="Convert UNIMARC records between XML, JSON, and ISO 2709")
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="Convert records between formats")
    p_convert.add_argument("--from", dest="from_format", choices=["xml", "json", "iso2709"], required=True)
    p_convert.add_argument("--to", dest="to_format", choices=["xml", "json", "iso2709"], required=True)
    p_convert.add_argument("--input", required=True)
    p_convert.add_argument("--output")
    p_convert.add_argument("--pretty", action="store_true")
    p_convert.add_argument("--fix-leader", action=argparse.BooleanOptionalAction, default=True)
    p_convert.set_defaults(func=cmd_convert)

    p_inspect = sub.add_parser("inspect", help="Inspect an input file")
    p_inspect.add_argument("--format", choices=["xml", "json", "iso2709"], required=True)
    p_inspect.add_argument("--input", required=True)
    p_inspect.add_argument("--fix-leader", action=argparse.BooleanOptionalAction, default=True)
    p_inspect.set_defaults(func=cmd_inspect)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:  # noqa: BLE001
        emit(
            {
                "ok": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                "warnings": [],
            },
            exit_code=1,
        )


if __name__ == "__main__":
    main()
