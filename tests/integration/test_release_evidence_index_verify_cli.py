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


def test_release_evidence_index_verify_root_all_pass(capsys, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "v1.9.0")
    _write_valid_evidence_dir(root / "v1.10.0")

    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["evidence_dir_count"] == 2
    assert payload["passed_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["checked_file_count"] == 4
    assert payload["index_hash"] is not None
    assert len(payload["index_hash"]) == 64
    for r in payload["results"]:
        assert r["status"] == "pass"


def test_release_evidence_index_verify_default_root_all_pass(capsys, tmp_path, monkeypatch):
    _write_valid_evidence_dir(tmp_path / "evidence")
    monkeypatch.chdir(tmp_path)

    result = main([
        "release-evidence-index-verify",
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["evidence_root"] is not None


def test_release_evidence_index_verify_list_all_pass(capsys, tmp_path):
    dir1 = tmp_path / "evidence1"
    dir2 = tmp_path / "evidence2"
    _write_valid_evidence_dir(dir1)
    _write_valid_evidence_dir(dir2)

    list_path = tmp_path / "evidence-list.txt"
    list_path.write_text(
        "\n".join([
            "",
            "# comment",
            str(dir1),
            "",
            str(dir2),
        ]) + "\n",
        encoding="utf-8",
    )

    result = main([
        "release-evidence-index-verify",
        "--evidence-list", str(list_path),
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["evidence_dir_count"] == 2
    assert isinstance(payload["evidence_list"], str)
    assert payload["evidence_list"].endswith("evidence-list.txt")
    assert not isinstance(payload["evidence_list"], list)


def test_release_evidence_index_verify_one_bad_fails(capsys, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "good")
    _write_valid_evidence_dir(root / "bad")
    (root / "bad" / "SHA256SUMS.txt").write_text(
        f"{'0' * 64}  full_release_evidence_manifest.json\n"
        f"{'0' * 64}  full_release_evidence_manifest.md\n",
        encoding="utf-8",
    )

    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert payload["passed_count"] == 1
    assert payload["failed_count"] == 1
    assert any("release evidence verification failed" in reason for reason in payload["reasons"])
    bad_result = [r for r in payload["results"] if r["status"] == "fail"][0]
    assert any("SHA256 mismatch" in reason for reason in bad_result["reasons"])


def test_release_evidence_index_verify_fail_fast(capsys, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "bad")
    (root / "bad" / "SHA256SUMS.txt").write_text(
        f"{'0' * 64}  full_release_evidence_manifest.json\n"
        f"{'0' * 64}  full_release_evidence_manifest.md\n",
        encoding="utf-8",
    )
    _write_valid_evidence_dir(root / "good")

    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
        "--fail-fast",
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert len(payload["results"]) == 1
    assert payload["failed_count"] == 1


def test_release_evidence_index_verify_markdown_output(capsys, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "v1.9.0")
    _write_valid_evidence_dir(root / "v1.10.0")

    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
        "--output", "markdown",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    assert "Release Evidence Index Verification" in stdout_text
    assert "Status: `pass`" in stdout_text
    assert "Evidence dir count" in stdout_text
    assert "Index hash" in stdout_text


def test_release_evidence_index_verify_no_dirs_found(capsys, tmp_path):
    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(tmp_path / "empty"),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert any("No evidence directories found" in reason for reason in payload["reasons"])


def test_release_evidence_index_verify_argument_conflict(capsys, tmp_path):
    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(tmp_path),
        "--evidence-list", str(tmp_path / "list.txt"),
    ])
    assert result != 0

    captured = capsys.readouterr()
    assert "Cannot use both" in captured.err or "Cannot use both" in captured.out


def test_release_evidence_index_verify_duplicate_list_fails(capsys, tmp_path):
    dir1 = tmp_path / "evidence1"
    _write_valid_evidence_dir(dir1)

    list_path = tmp_path / "evidence-list.txt"
    list_path.write_text(
        "\n".join([
            str(dir1),
            str(dir1),
        ]) + "\n",
        encoding="utf-8",
    )

    result = main([
        "release-evidence-index-verify",
        "--evidence-list", str(list_path),
    ])
    assert result != 0

    payload = json.loads(capsys.readouterr().out)
    assert any("Duplicate evidence directory" in reason for reason in payload["reasons"])


def test_release_evidence_index_verify_no_db_access(capsys, monkeypatch, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "v1.9.0")
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))

    result = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
    ])
    assert result == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"


def test_release_evidence_index_verify_deterministic_hash(capsys, tmp_path):
    root = tmp_path / "releases"
    _write_valid_evidence_dir(root / "v1.9.0")
    _write_valid_evidence_dir(root / "v1.10.0")

    result1 = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
    ])
    assert result1 == 0
    hash1 = json.loads(capsys.readouterr().out)["index_hash"]

    result2 = main([
        "release-evidence-index-verify",
        "--evidence-root", str(root),
    ])
    assert result2 == 0
    hash2 = json.loads(capsys.readouterr().out)["index_hash"]

    assert hash1 == hash2
