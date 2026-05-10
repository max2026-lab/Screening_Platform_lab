import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lawful_anomaly_screening.releases import evidence_index_export_smoke_report as smoke_report
from lawful_anomaly_screening.cli import main


def _write_valid_evidence_dir(evidence_dir: Path) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "evidence_type": "full_release_evidence_manifest",
        "release_status": "passed",
        "phases_verified": ["phase27", "phase28"],
        "results": {"pytest_status": "passed"},
        "artifacts": [
            "full_release_evidence_manifest.json",
            "full_release_evidence_manifest.md",
            "SHA256SUMS.txt",
        ],
    }
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    md_text = (
        "# Full Release Evidence Manifest\n\n"
        "Phase 28 full release evidence verification summary.\n"
    )

    json_path = evidence_dir / "full_release_evidence_manifest.json"
    md_path = evidence_dir / "full_release_evidence_manifest.md"
    sums_path = evidence_dir / "SHA256SUMS.txt"

    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    def _sha256_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    sums_text = (
        f"{_sha256_text(json_text)}  full_release_evidence_manifest.json\n"
        f"{_sha256_text(md_text)}  full_release_evidence_manifest.md\n"
    )
    sums_path.write_text(sums_text, encoding="utf-8", newline="\n")


_TEST_ROOT = Path(".test-release-evidence-index-export-smoke-report")


def _test_dir(name: str) -> Path:
    path = _TEST_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# --- API tests ---


def test_report_all_passes():
    root = _test_dir("report_all")
    _write_valid_evidence_dir(root / "v1.10.0")
    out = _TEST_ROOT / "report_all_out"
    result = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=out,
        formats=["json", "markdown", "both"],
    )
    assert result["status"] == "pass"
    assert result["schema"]["version"] == "v1.15.0"
    report_dir = Path(result["report_dir"])
    assert report_dir.exists()
    assert (report_dir / "release_evidence_index_export_smoke_report.json").exists()
    assert (report_dir / "release_evidence_index_export_smoke_report.md").exists()
    assert (report_dir / "SHA256SUMS.txt").exists()

    sums_lines = (
        (report_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").strip().splitlines()
    )
    assert len(sums_lines) == 2
    assert all("release_evidence_index_export_smoke_report" in line for line in sums_lines)
    assert not any("SHA256SUMS.txt" in line for line in sums_lines)

    smoke = result["smoke_result"]
    assert smoke["status"] == "pass"
    assert result["formats_run"] == ["json", "markdown", "both"]


def test_report_json_format_only():
    root = _test_dir("report_json")
    _write_valid_evidence_dir(root / "v1.10.0")
    out = _TEST_ROOT / "report_json_out"
    result = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=out,
        formats=["json"],
    )
    assert result["status"] == "pass"
    assert result["formats_run"] == ["json"]
    smoke = result["smoke_result"]
    assert smoke["status"] == "pass"
    assert len(smoke["results"]) == 1
    assert smoke["results"][0]["format"] == "json"


def test_report_fails_on_bad_evidence_but_writes_artifacts():
    root = _test_dir("report_bad")
    evidence_dir = root / "v1.10.0"
    evidence_dir.mkdir(parents=True)
    out = _TEST_ROOT / "report_bad_out"
    result = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=out,
        formats=["json"],
    )
    assert result["status"] == "fail"
    report_dir = Path(result["report_dir"])
    assert report_dir.exists()
    assert (report_dir / "release_evidence_index_export_smoke_report.json").exists()
    assert (report_dir / "release_evidence_index_export_smoke_report.md").exists()
    assert (report_dir / "SHA256SUMS.txt").exists()

    md_text = (report_dir / "release_evidence_index_export_smoke_report.md").read_text(
        encoding="utf-8"
    )
    assert "fail" in md_text.lower()


def test_report_fails_when_output_root_inside_evidence_root():
    root = _test_dir("report_nested")
    _write_valid_evidence_dir(root / "v1.10.0")
    result = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=root / "out",
        formats=["json"],
    )
    assert result["status"] == "fail"
    assert any("output_root must not be the same as or inside evidence_root" in r for r in result["reasons"])
    assert result["report_dir"] is None


def test_report_deterministic_hashes():
    root = _test_dir("report_deterministic")
    _write_valid_evidence_dir(root / "v1.10.0")
    out1 = _TEST_ROOT / "report_deterministic_out1"
    out2 = _TEST_ROOT / "report_deterministic_out2"
    result1 = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=out1,
        formats=["both"],
    )
    result2 = smoke_report.run_release_evidence_index_export_smoke_report(
        evidence_root=root,
        output_root=out2,
        formats=["both"],
    )
    assert result1["status"] == "pass"
    assert result2["status"] == "pass"
    # Smoke artifacts should have identical hashes since evidence is the same
    artifacts1 = result1["smoke_result"]["results"][0]["export_artifacts"]
    artifacts2 = result2["smoke_result"]["results"][0]["export_artifacts"]
    for a1, a2 in zip(artifacts1, artifacts2):
        assert a1["sha256"] == a2["sha256"], f"hash mismatch for {a1['name']}"


# --- CLI tests ---


def test_cli_report_all_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    result = main([
        "release-evidence-index-export-smoke-report",
        "--evidence-root", str(root),
        "--output-root", str(tmp_path / "out"),
        "--format", "all",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["schema"]["version"] == "v1.15.0"
    report_dir = Path(payload["report_dir"])
    assert report_dir.exists()
    assert (report_dir / "SHA256SUMS.txt").exists()


def test_cli_report_json_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    result = main([
        "release-evidence-index-export-smoke-report",
        "--evidence-root", str(root),
        "--output-root", str(tmp_path / "out"),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["formats_run"] == ["json"]


def test_cli_report_fails_on_bad_evidence(capsys, tmp_path):
    root = tmp_path / "evidence"
    evidence_dir = root / "v1.10.0"
    evidence_dir.mkdir(parents=True)
    result = main([
        "release-evidence-index-export-smoke-report",
        "--evidence-root", str(root),
        "--output-root", str(tmp_path / "out"),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    report_dir = Path(payload["report_dir"])
    assert report_dir.exists()
    assert (report_dir / "release_evidence_index_export_smoke_report.json").exists()


def test_cli_report_output_root_inside_evidence_root(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    result = main([
        "release-evidence-index-export-smoke-report",
        "--evidence-root", str(root),
        "--output-root", str(root / "out"),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("output_root must not be the same as or inside evidence_root" in r for r in payload["reasons"])


def test_cli_report_no_db_access(capsys, monkeypatch, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = main([
        "release-evidence-index-export-smoke-report",
        "--evidence-root", str(root),
        "--output-root", str(tmp_path / "out"),
        "--format", "all",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"


def test_cli_report_missing_output_root(tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    with pytest.raises(SystemExit) as exc_info:
        main([
            "release-evidence-index-export-smoke-report",
            "--evidence-root", str(root),
            "--format", "json",
        ])
    assert exc_info.value.code != 0
