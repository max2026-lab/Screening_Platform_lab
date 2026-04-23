from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
import sys

from . import __version__
from .exceptions import LegalGateError
from .settings import load_settings


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_baseline() -> dict:
    return _load_json(load_settings().baseline_path)


def _legal_gate_passed() -> bool:
    baseline = _load_baseline()
    return bool(baseline["legal"]["gate_required_before_analysis"])


def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_show_config(_: argparse.Namespace) -> int:
    settings = load_settings()
    print(json.dumps(
        {
            "db_path": str(settings.db_path),
            "baseline_path": str(settings.baseline_path),
            "logging_config_path": str(settings.logging_config_path),
            "export_precision_path": str(settings.export_precision_path),
        },
        indent=2,
    ))
    return 0


def cmd_show_baseline(_: argparse.Namespace) -> int:
    print(json.dumps(_load_baseline(), indent=2))
    return 0


def cmd_init_db(_: argparse.Namespace) -> int:
    from .db.sqlite import init_db

    init_db(load_settings().db_path)
    print("ok")
    return 0


def cmd_validate_aoi(_: argparse.Namespace) -> int:
    print("AOI validation scaffold ready")
    return 0


def cmd_legal_check(_: argparse.Namespace) -> int:
    if _legal_gate_passed():
        print("legal gate passed")
        return 0
    raise LegalGateError("legal gate failed")


def cmd_create_run(_: argparse.Namespace) -> int:
    if not _legal_gate_passed():
        raise SystemExit("legal gate failed")
    print("run created")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lawful-anomaly-screening")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "version": cmd_version,
        "show-config": cmd_show_config,
        "show-baseline": cmd_show_baseline,
        "init-db": cmd_init_db,
        "validate-aoi": cmd_validate_aoi,
        "legal-check": cmd_legal_check,
        "create-run": cmd_create_run,
    }
    for name, func in commands.items():
        p = sub.add_parser(name)
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except LegalGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
