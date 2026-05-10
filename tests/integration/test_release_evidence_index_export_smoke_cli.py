import hashlib
import json
import shutil
from pathlib import Path

from lawful_anomaly_screening.releases import evidence_index_export_smoke as smoke
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


_TEST_ROOT = Path(".test-release-evidence-index-export-smoke")


def _test_dir(name: str) -> Path:
    path = _TEST_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# --- API tests ---


def test_smoke_json_format_passes():
    root = _test_dir("smoke_json")
    _write_valid_evidence_dir(root / "v1.10.0")
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out",
        formats=["json"],
    )
    assert result["status"] == "pass"
    assert result["schema"]["version"] == "v1.14.0"
    assert result["formats_run"] == ["json"]
    fmt_result = result["results"][0]
    assert fmt_result["format"] == "json"
    assert fmt_result["export_status"] == "pass"
    assert fmt_result["verify_status"] == "pass"
    assert fmt_result["status"] == "pass"
    assert any(a["name"] == "release_evidence_index.json" for a in fmt_result["export_artifacts"])
    assert any(a["name"] == "SHA256SUMS.txt" for a in fmt_result["export_artifacts"])


def test_smoke_markdown_format_passes():
    root = _test_dir("smoke_md")
    _write_valid_evidence_dir(root / "v1.10.0")
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out",
        formats=["markdown"],
    )
    assert result["status"] == "pass"
    assert result["formats_run"] == ["markdown"]
    fmt_result = result["results"][0]
    assert fmt_result["format"] == "markdown"
    assert fmt_result["export_status"] == "pass"
    assert fmt_result["verify_status"] == "pass"
    assert fmt_result["status"] == "pass"
    assert any(a["name"] == "release_evidence_index.md" for a in fmt_result["export_artifacts"])


def test_smoke_both_format_passes():
    root = _test_dir("smoke_both")
    _write_valid_evidence_dir(root / "v1.10.0")
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out",
        formats=["both"],
    )
    assert result["status"] == "pass"
    assert result["formats_run"] == ["both"]
    fmt_result = result["results"][0]
    assert fmt_result["format"] == "both"
    assert fmt_result["export_status"] == "pass"
    assert fmt_result["verify_status"] == "pass"
    assert fmt_result["status"] == "pass"
    assert len(fmt_result["export_artifacts"]) == 3


def test_smoke_all_formats_passes():
    root = _test_dir("smoke_all")
    _write_valid_evidence_dir(root / "v1.10.0")
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out",
        formats=None,
    )
    assert result["status"] == "pass"
    assert result["formats_run"] == ["json", "markdown", "both"]
    for fmt_result in result["results"]:
        assert fmt_result["export_status"] == "pass"
        assert fmt_result["verify_status"] == "pass"
        assert fmt_result["status"] == "pass"


def test_smoke_cleans_previous_run():
    root = _test_dir("smoke_clean")
    _write_valid_evidence_dir(root / "v1.10.0")
    out = root / "out"
    smoke_dir = out / "release-evidence-index-export-smoke" / "json"
    smoke_dir.mkdir(parents=True)
    (smoke_dir / "old_file.txt").write_text("old", encoding="utf-8")
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=out,
        formats=["json"],
    )
    assert result["status"] == "pass"
    assert not (smoke_dir / "old_file.txt").exists()


def test_smoke_fails_when_evidence_bad():
    root = _test_dir("smoke_bad_evidence")
    evidence_dir = root / "v1.10.0"
    evidence_dir.mkdir(parents=True)
    # Missing required files
    result = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out",
        formats=["json"],
    )
    assert result["status"] == "fail"
    fmt_result = result["results"][0]
    assert fmt_result["format"] == "json"
    assert fmt_result["export_status"] == "fail"
    assert fmt_result["verify_status"] == "skipped"
    assert fmt_result["status"] == "fail"


def test_smoke_deterministic_hash():
    root = _test_dir("smoke_deterministic")
    _write_valid_evidence_dir(root / "v1.10.0")
    result1 = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out1",
        formats=["both"],
    )
    result2 = smoke.run_release_evidence_index_export_smoke(
        evidence_root=root,
        output_root=root / "out2",
        formats=["both"],
    )
    assert result1["status"] == "pass"
    assert result2["status"] == "pass"
    artifacts1 = result1["results"][0]["export_artifacts"]
    artifacts2 = result2["results"][0]["export_artifacts"]
    for a1, a2 in zip(artifacts1, artifacts2):
        assert a1["sha256"] == a2["sha256"], f"hash mismatch for {a1['name']}"


# --- CLI tests ---


def test_cli_smoke_all_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    result = main([
        "release-evidence-index-export-smoke",
        "--evidence-root", str(root),
        "--output-root", str(root / "out"),
        "--format", "all",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["schema"]["version"] == "v1.14.0"
    assert payload["formats_run"] == ["json", "markdown", "both"]


def test_cli_smoke_json_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    result = main([
        "release-evidence-index-export-smoke",
        "--evidence-root", str(root),
        "--output-root", str(root / "out"),
        "--format", "json",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["formats_run"] == ["json"]


def test_cli_smoke_fails_on_bad_evidence(capsys, tmp_path):
    root = tmp_path / "evidence"
    evidence_dir = root / "v1.10.0"
    evidence_dir.mkdir(parents=True)
    result = main([
        "release-evidence-index-export-smoke",
        "--evidence-root", str(root),
        "--output-root", str(root / "out"),
        "--format", "json",
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert payload["results"][0]["export_status"] == "fail"


def test_cli_smoke_no_db_access(capsys, monkeypatch, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = main([
        "release-evidence-index-export-smoke",
        "--evidence-root", str(root),
        "--output-root", str(root / "out"),
        "--format", "all",
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
