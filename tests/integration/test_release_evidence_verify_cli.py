import hashlib
import json
from pathlib import Path

from lawful_anomaly_screening.cli import main


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_valid_evidence_dir(
    evidence_dir: Path,
    *,
    json_payload: dict | None = None,
    markdown_text: str | None = None,
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)

    payload = json_payload or {
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
    md_text = markdown_text or (
        "# Full Release Evidence Manifest\n\n"
        "Phase 28 full release evidence verification summary.\n"
    )

    json_path = evidence_dir / "full_release_evidence_manifest.json"
    md_path = evidence_dir / "full_release_evidence_manifest.md"
    sums_path = evidence_dir / "SHA256SUMS.txt"

    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    sums_text = (
        f"{_sha256_text(json_text)}  full_release_evidence_manifest.json\n"
        f"{_sha256_text(md_text)}  full_release_evidence_manifest.md\n"
    )
    sums_path.write_text(sums_text, encoding="utf-8", newline="\n")


def test_release_evidence_verify_passes(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["required_files_present"] is True
    assert payload["json_manifest_valid"] is True
    assert payload["markdown_manifest_valid"] is True
    assert payload["sha256sums_valid"] is True
    assert payload["checked_file_count"] == 2
    assert payload["reasons"] == []


def test_release_evidence_verify_markdown_output(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
        "--output", "markdown",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    assert "Release Evidence Verification" in stdout_text
    assert "Status: `pass`" in stdout_text
    assert "Checked file count" in stdout_text


def test_release_evidence_verify_missing_file_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    (evidence_dir / "full_release_evidence_manifest.md").unlink()

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert any("Missing required file: full_release_evidence_manifest.md" in reason for reason in payload["reasons"])


def test_release_evidence_verify_bad_json_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    (evidence_dir / "full_release_evidence_manifest.json").write_text(
        "{not-json}\n",
        encoding="utf-8",
        newline="\n",
    )

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert any("Invalid JSON manifest" in reason for reason in payload["reasons"])


def test_release_evidence_verify_bad_markdown_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(
        evidence_dir,
        markdown_text="ordinary text without the required markers\n",
    )

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert any("Markdown manifest" in reason for reason in payload["reasons"])


def test_release_evidence_verify_hash_mismatch_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    json_path = evidence_dir / "full_release_evidence_manifest.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["status"] = "tampered"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert any("SHA256 mismatch" in reason for reason in output["reasons"])


def test_release_evidence_verify_malformed_sha256sums_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    (evidence_dir / "SHA256SUMS.txt").write_text(
        "\n".join([
            "malformed line",
            "1234  full_release_evidence_manifest.json",
            "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz  full_release_evidence_manifest.md",
        ]) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert any("Malformed SHA256SUMS line" in reason for reason in output["reasons"])


def test_release_evidence_verify_unexpected_checksum_entry_fails(capsys, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    sums_path = evidence_dir / "SHA256SUMS.txt"
    sums_path.write_text(
        sums_path.read_text(encoding="utf-8")
        + f"{'0' * 64}  unexpected.txt\n",
        encoding="utf-8",
        newline="\n",
    )

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result != 0

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "fail"
    assert any("Unexpected checksum entry: unexpected.txt" in reason for reason in output["reasons"])


def test_release_evidence_verify_no_db_access(capsys, monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    _write_valid_evidence_dir(evidence_dir)
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))

    result = main([
        "release-evidence-verify",
        "--evidence-dir", str(evidence_dir),
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
