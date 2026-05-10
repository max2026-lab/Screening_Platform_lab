import hashlib
import json
import shutil
from pathlib import Path

import pytest

from lawful_anomaly_screening.releases import evidence_index_exporter as exporter
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


_TEST_ROOT = Path(".test-release-evidence-index-export")


def _test_dir(name: str) -> Path:
    path = _TEST_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def test_export_release_evidence_index_root_all_pass():
    root = _test_dir("root_pass")
    _write_valid_evidence_dir(root / "v1.10.0")
    _write_valid_evidence_dir(root / "v1.11.0")

    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )

    assert result["status"] == "pass"
    assert result["output_dir"] is not None
    assert len(result["artifacts"]) == 3  # json, md, SHA256SUMS.txt

    out = Path(result["output_dir"])
    assert (out / "release_evidence_index.json").exists()
    assert (out / "release_evidence_index.md").exists()
    assert (out / "SHA256SUMS.txt").exists()

    json_payload = json.loads((out / "release_evidence_index.json").read_text(encoding="utf-8"))
    assert json_payload["schema"]["version"] == "v1.12.0"
    assert json_payload["index_hash"] is not None
    assert json_payload["evidence_dir_count"] == 2
    assert json_payload["passed_count"] == 2
    assert json_payload["failed_count"] == 0

    # export_artifacts manifest must exist with 3 entries
    artifacts = json_payload.get("export_artifacts", [])
    assert len(artifacts) == 3
    names = {a["name"] for a in artifacts}
    assert names == {"release_evidence_index.json", "release_evidence_index.md", "SHA256SUMS.txt"}

    # JSON self-hash must be None to avoid circular dependency
    json_artifact = next(a for a in artifacts if a["name"] == "release_evidence_index.json")
    assert json_artifact["sha256"] is None

    # MD hash must be populated after markdown is finalized
    md_artifact = next(a for a in artifacts if a["name"] == "release_evidence_index.md")
    assert md_artifact["sha256"] is not None
    assert len(md_artifact["sha256"]) == 64

    # Markdown must contain Exported Artifacts section with JSON hash reference
    md_text = (out / "release_evidence_index.md").read_text(encoding="utf-8")
    assert "## Exported Artifacts" in md_text
    # The markdown references the first-pass JSON hash, so it should appear
    assert "release_evidence_index.json" in md_text


def test_export_release_evidence_index_fails_when_verification_fails():
    root = _test_dir("root_fail")
    _write_valid_evidence_dir(root / "good")
    bad = root / "bad"
    bad.mkdir(parents=True, exist_ok=True)
    # Create an evidence dir with bad SHA256SUMS
    (bad / "full_release_evidence_manifest.json").write_text("{}", encoding="utf-8")
    (bad / "full_release_evidence_manifest.md").write_text("# Phase 28\n", encoding="utf-8")
    (bad / "SHA256SUMS.txt").write_text(
        f"{'0'*64}  full_release_evidence_manifest.json\n"
        f"{'0'*64}  full_release_evidence_manifest.md\n",
        encoding="utf-8",
    )

    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )

    assert result["status"] == "fail"
    assert result["output_dir"] is None
    assert not (root / "export").exists()


def test_export_release_evidence_index_list_mode():
    root = _test_dir("list_mode")
    dir1 = root / "evidence1"
    dir2 = root / "evidence2"
    _write_valid_evidence_dir(dir1)
    _write_valid_evidence_dir(dir2)

    list_path = root / "evidence-list.txt"
    list_path.write_text(f"{dir1}\n{dir2}\n", encoding="utf-8")

    result = exporter.export_release_evidence_index(
        evidence_list=[dir1, dir2],
        evidence_list_path=str(list_path),
        output_dir=root / "export",
        fmt="both",
    )

    assert result["status"] == "pass"
    assert result["verify_result"]["evidence_list"] is not None


def test_export_release_evidence_index_deterministic_hash():
    root = _test_dir("deterministic")
    _write_valid_evidence_dir(root / "v1.10.0")

    result1 = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export1",
        fmt="json",
    )
    result2 = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export2",
        fmt="json",
    )

    assert result1["status"] == "pass"
    assert result2["status"] == "pass"

    out1 = Path(result1["output_dir"])
    out2 = Path(result2["output_dir"])

    json1 = (out1 / "release_evidence_index.json").read_text(encoding="utf-8")
    json2 = (out2 / "release_evidence_index.json").read_text(encoding="utf-8")
    assert json1 == json2


def test_export_release_evidence_index_sha256sums_valid():
    root = _test_dir("sha256sums")
    _write_valid_evidence_dir(root / "v1.10.0")

    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )

    assert result["status"] == "pass"
    out = Path(result["output_dir"])
    sums_text = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")

    lines = sums_text.strip().splitlines()
    # SHA256SUMS.txt must list exactly json and md, not itself
    assert len(lines) == 2
    names = {line.split("  ", 1)[1] for line in lines}
    assert names == {"release_evidence_index.json", "release_evidence_index.md"}

    for line in lines:
        h, name = line.split("  ", 1)
        artifact = out / name
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == h


def test_cli_release_evidence_index_export_root(capsys, tmp_path):
    _write_valid_evidence_dir(tmp_path / "v1.10.0")

    result = main([
        "release-evidence-index-export",
        "--evidence-root", str(tmp_path),
        "--output-dir", str(tmp_path / "export"),
        "--format", "json",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
    assert (tmp_path / "export" / "release_evidence_index.json").exists()


def test_cli_release_evidence_index_export_fails_on_bad_evidence(capsys, tmp_path):
    (tmp_path / "bad").mkdir()

    result = main([
        "release-evidence-index-export",
        "--evidence-root", str(tmp_path),
        "--output-dir", str(tmp_path / "export"),
        "--format", "json",
    ])
    assert result != 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "fail"
    assert not (tmp_path / "export").exists()


def test_cli_release_evidence_index_export_argument_conflict(capsys, tmp_path):
    result = main([
        "release-evidence-index-export",
        "--evidence-root", str(tmp_path),
        "--evidence-list", str(tmp_path / "list.txt"),
    ])
    assert result != 0

    captured = capsys.readouterr()
    assert "Cannot use both" in captured.err or "Cannot use both" in captured.out


def test_cli_release_evidence_index_export_no_db_access(capsys, monkeypatch, tmp_path):
    _write_valid_evidence_dir(tmp_path / "v1.10.0")
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))

    result = main([
        "release-evidence-index-export",
        "--evidence-root", str(tmp_path),
        "--output-dir", str(tmp_path / "export"),
        "--format", "json",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    payload = json.loads(stdout_text)
    assert payload["status"] == "pass"
