"""Command line interface for gcode-guard.

Usage:
    gcode-guard program.nc [--config limits.json] [--format text|json]

Exit codes: 0 = no errors (warnings allowed), 1 = at least one error
finding, 2 = usage or file error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checker import ERROR, Config, check_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gcode-guard",
        description="Static checker for CNC G-code programs "
        "(feed/spindle state, machine envelope, arc consistency).",
    )
    parser.add_argument("program", help="path to the .nc/.gcode program to check")
    parser.add_argument(
        "--config",
        metavar="JSON",
        help="JSON config with envelope limits (x_min/x_max/...), "
        "safe_z and arc_tolerance",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    config = Config()
    if args.config:
        try:
            config = Config.from_json(args.config)
        except (OSError, ValueError) as exc:
            print("gcode-guard: cannot load config: %s" % exc, file=sys.stderr)
            return 2

    path = Path(args.program)
    if not path.is_file():
        print("gcode-guard: no such file: %s" % path, file=sys.stderr)
        return 2

    findings = check_file(path, config)
    errors = sum(1 for f in findings if f.severity == ERROR)
    warnings = len(findings) - errors

    if args.format == "json":
        payload = {
            "file": str(path),
            "findings": [f.to_dict() for f in findings],
            "summary": {"errors": errors, "warnings": warnings},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print("%s:%d: %s [%s] %s" % (path, f.line, f.severity, f.rule, f.message))
        print("%s: %d error(s), %d warning(s)" % (path, errors, warnings))

    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
