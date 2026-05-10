from __future__ import annotations

from pathlib import Path
from typing import Literal

from .evidence_index_exporter import export_release_evidence_index
from .evidence_index_export_verifier import verify_release_evidence_index_export

SCHEMA_VERSION = "v1.14.0"

_FormatLiteral = Literal["json", "markdown", "both"]


def run_release_evidence_index_export_smoke(
    evidence_root: str | Path,
    output_root: str | Path,
    formats: list[_FormatLiteral] | None = None,
) -> dict:
    """Run a local round-trip smoke of V1.12 export + V1.13 verify.

    For each selected format:
    1. Export release evidence index artifacts deterministically.
    2. Verify the produced export directory.
    3. Record pass/fail details.

    The command is offline, requires no DB, no network, and does not
    mutate source evidence directories.
    """
    evidence_path = Path(evidence_root).resolve()
    out_root = Path(output_root).resolve()

    # Safety: output_root must not be evidence_root or inside it
    try:
        out_root.relative_to(evidence_path)
        return {
            "schema": {
                "version": SCHEMA_VERSION,
                "name": "release_evidence_index_export_smoke",
            },
            "evidence_root": str(evidence_path).replace("\\", "/"),
            "output_root": str(out_root).replace("\\", "/"),
            "formats_run": formats if formats else ["json", "markdown", "both"],
            "results": [],
            "status": "fail",
            "reasons": ["output_root must not be the same as or inside evidence_root"],
        }
    except ValueError:
        pass

    smoke_dir = out_root / "release-evidence-index-export-smoke"

    selected_formats: list[_FormatLiteral] = formats if formats else ["json", "markdown", "both"]

    results: list[dict] = []
    overall_pass = True

    for fmt in selected_formats:
        fmt_out = smoke_dir / fmt
        # Clean any previous run to keep deterministic
        if fmt_out.exists():
            _rmtree(fmt_out)
        fmt_out.mkdir(parents=True, exist_ok=True)

        export_result = export_release_evidence_index(
            evidence_root=evidence_path,
            output_dir=fmt_out,
            fmt=fmt,
        )

        verify_result: dict | None = None
        if export_result.get("status") == "pass":
            verify_result = verify_release_evidence_index_export(fmt_out)

        fmt_pass = (
            export_result.get("status") == "pass"
            and verify_result is not None
            and verify_result.get("status") == "pass"
        )
        if not fmt_pass:
            overall_pass = False

        format_record: dict = {
            "format": fmt,
            "export_status": export_result.get("status", "fail"),
            "export_dir": str(export_result.get("output_dir", str(fmt_out))).replace("\\", "/"),
            "export_artifacts": [
                {"name": a["name"], "sha256": a["sha256"]}
                for a in export_result.get("artifacts", [])
            ],
            "verify_status": verify_result.get("status", "skipped") if verify_result else "skipped",
            "verify_reasons": verify_result.get("reasons", []) if verify_result else [],
            "verify_sha256sums_entries": verify_result.get("sha256sums_entries", []) if verify_result else [],
            "status": "pass" if fmt_pass else "fail",
        }
        results.append(format_record)

    return {
        "schema": {
            "version": SCHEMA_VERSION,
            "name": "release_evidence_index_export_smoke",
        },
        "evidence_root": str(evidence_path).replace("\\", "/"),
        "output_root": str(out_root).replace("\\", "/"),
        "formats_run": selected_formats,
        "results": results,
        "status": "pass" if overall_pass else "fail",
        "reasons": [],
    }


def _rmtree(path: Path) -> None:
    """Recursively remove a directory tree."""
    for item in path.iterdir():
        if item.is_dir():
            _rmtree(item)
        else:
            item.unlink()
    path.rmdir()
