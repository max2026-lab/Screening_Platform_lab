import hashlib
import json
import shutil
from pathlib import Path

from lawful_anomaly_screening.releases import evidence_index_exporter as exporter
from lawful_anomaly_screening.releases import evidence_index_export_verifier as verifier
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


_TEST_ROOT = Path(".test-release-evidence-index-export-verify")


def _test_dir(name: str) -> Path:
    path = _TEST_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _create_export_both(name: str) -> Path:
    root = _test_dir(name)
    _write_valid_evidence_dir(root / "v1.10.0")
    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    assert result["status"] == "pass"
    return Path(result["output_dir"])


def _create_export_json_only(name: str) -> Path:
    root = _test_dir(name)
    _write_valid_evidence_dir(root / "v1.10.0")
    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="json",
    )
    assert result["status"] == "pass"
    return Path(result["output_dir"])


def _create_export_markdown_only(name: str) -> Path:
    root = _test_dir(name)
    _write_valid_evidence_dir(root / "v1.10.0")
    result = exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="markdown",
    )
    assert result["status"] == "pass"
    return Path(result["output_dir"])


# --- both mode tests ---


def test_verify_both_mode_passes():
    export_dir = _create_export_both("both_pass")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "pass"
    assert result["format_detected"] == "both"
    assert result["json_valid"] is True
    assert result["markdown_valid"] is True
    assert len(result["sha256sums_entries"]) == 2


def test_verify_both_missing_sha256sums():
    export_dir = _create_export_both("both_missing_sums")
    (export_dir / "SHA256SUMS.txt").unlink()
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert "SHA256SUMS.txt is missing" in result["reasons"]


def test_verify_both_sha256sums_self_reference():
    export_dir = _create_export_both("both_self_ref")
    sums_path = export_dir / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    fake_hash = "0" * 64
    sums_path.write_text(f"{sums_text}{fake_hash}  SHA256SUMS.txt\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert "must not include its own hash" in result["reasons"][0]


def test_verify_both_hash_mismatch():
    export_dir = _create_export_both("both_hash_mismatch")
    sums_path = export_dir / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    tampered = f"{'0'*64}  {lines[0].split('  ', 1)[1]}\n{lines[1]}\n"
    sums_path.write_text(tampered, encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Hash mismatch" in r for r in result["reasons"])


def test_verify_both_json_missing_on_disk():
    export_dir = _create_export_both("both_json_missing")
    (export_dir / "release_evidence_index.json").unlink()
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing on disk" in r and "json" in r.lower() for r in result["reasons"])


def test_verify_both_md_missing_on_disk():
    export_dir = _create_export_both("both_md_missing")
    (export_dir / "release_evidence_index.md").unlink()
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing on disk" in r and "md" in r.lower() for r in result["reasons"])


# --- json-only mode tests ---


def test_verify_json_mode_passes():
    export_dir = _create_export_json_only("json_pass")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "pass"
    assert result["format_detected"] == "json"
    assert result["json_valid"] is True
    assert result["markdown_valid"] is False
    assert len(result["sha256sums_entries"]) == 1
    assert result["sha256sums_entries"][0]["name"] == "release_evidence_index.json"


def test_verify_json_mode_missing_json_entry_in_sums():
    export_dir = _create_export_json_only("json_missing_entry")
    sums_path = export_dir / "SHA256SUMS.txt"
    sums_path.write_text("", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert "SHA256SUMS.txt is empty" in result["reasons"]


# --- markdown-only mode tests ---


def test_verify_markdown_mode_passes():
    export_dir = _create_export_markdown_only("md_pass")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "pass"
    assert result["format_detected"] == "markdown"
    assert result["json_valid"] is False
    assert result["markdown_valid"] is True
    assert len(result["sha256sums_entries"]) == 1
    assert result["sha256sums_entries"][0]["name"] == "release_evidence_index.md"


def test_verify_markdown_mode_no_json_mention():
    export_dir = _create_export_markdown_only("md_no_json")
    md_text = (export_dir / "release_evidence_index.md").read_text(encoding="utf-8")
    # The markdown verifier doesn't enforce "no json mention", but the exporter
    # should not mention JSON in markdown-only mode.
    assert "release_evidence_index.json" not in md_text


# --- JSON schema validation tests ---


def test_verify_bad_schema_version():
    export_dir = _create_export_both("bad_schema")
    json_path = export_dir / "release_evidence_index.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["schema"]["version"] = "v1.99.0"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Schema version mismatch" in r for r in result["reasons"])


def test_verify_missing_index_hash():
    export_dir = _create_export_both("missing_hash")
    json_path = export_dir / "release_evidence_index.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["index_hash"] = None
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Missing index_hash" in r for r in result["reasons"])


def test_verify_json_self_hash_not_null():
    export_dir = _create_export_both("self_hash_not_null")
    json_path = export_dir / "release_evidence_index.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    for artifact in payload["export_artifacts"]:
        if artifact["name"] == "release_evidence_index.json":
            artifact["sha256"] = "a" * 64
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("self-hash must be null" in r for r in result["reasons"])


def test_verify_json_missing_self_reference_note():
    export_dir = _create_export_both("bad_note")
    json_path = export_dir / "release_evidence_index.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    for artifact in payload["export_artifacts"]:
        if artifact["name"] == "release_evidence_index.json":
            artifact["note"] = "some other note"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("self-reference" in r.lower() or "circularity" in r.lower() for r in result["reasons"])


# --- markdown validation tests ---


def test_verify_md_missing_heading():
    export_dir = _create_export_both("md_bad_heading")
    md_path = export_dir / "release_evidence_index.md"
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text.replace("# Release Evidence Index Export", "# Something Else"), encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing '# Release Evidence Index Export' heading" in r for r in result["reasons"])


def test_verify_md_missing_index_hash():
    export_dir = _create_export_both("md_bad_hash_line")
    md_path = export_dir / "release_evidence_index.md"
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text.replace("- Index hash:", "- No hash:"), encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing Index hash line" in r for r in result["reasons"])


def test_verify_md_missing_evidence_directories_section():
    export_dir = _create_export_both("md_bad_evidence_dirs")
    md_path = export_dir / "release_evidence_index.md"
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text.replace("## Evidence Directories", "## Dirs"), encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing '## Evidence Directories'" in r for r in result["reasons"])


def test_verify_md_missing_exported_artifacts_section():
    export_dir = _create_export_both("md_bad_artifacts")
    md_path = export_dir / "release_evidence_index.md"
    text = md_path.read_text(encoding="utf-8")
    md_path.write_text(text.replace("## Exported Artifacts", "## Artifacts"), encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("missing '## Exported Artifacts'" in r for r in result["reasons"])


# --- cross-check tests ---


def test_verify_md_hash_cross_check_mismatch():
    export_dir = _create_export_both("md_cross_mismatch")
    json_path = export_dir / "release_evidence_index.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    for artifact in payload["export_artifacts"]:
        if artifact["name"] == "release_evidence_index.md":
            artifact["sha256"] = "b" * 64
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Markdown hash mismatch" in r for r in result["reasons"])


# --- malformed / unsupported SHA256SUMS tests ---


def test_verify_malformed_sums_line():
    export_dir = _create_export_both("malformed_line")
    sums_path = export_dir / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    sums_path.write_text(f"{lines[0]}\nbadline\n{lines[1]}\n", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Malformed SHA256SUMS line" in r for r in result["reasons"])


def test_verify_unsupported_sums_entry():
    export_dir = _create_export_both("unsupported_entry")
    sums_path = export_dir / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    fake_hash = "a" * 64
    sums_path.write_text(f"{lines[0]}\n{fake_hash}  extra.txt\n{lines[1]}\n", encoding="utf-8")
    (export_dir / "extra.txt").write_text("extra", encoding="utf-8")
    result = verifier.verify_release_evidence_index_export(export_dir)
    assert result["status"] == "fail"
    assert any("Unsupported artifact" in r for r in result["reasons"])


# --- CLI tests ---


def test_cli_verify_both_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"


def test_cli_verify_json_only_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="json",
    )
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["format_detected"] == "json"


def test_cli_verify_markdown_only_pass(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="markdown",
    )
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"
    assert payload["format_detected"] == "markdown"


def test_cli_verify_fails_on_bad_hash(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    sums_path = root / "export" / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    tampered = f"{'0'*64}  {lines[0].split('  ', 1)[1]}\n{lines[1]}\n"
    sums_path.write_text(tampered, encoding="utf-8")
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"


def test_cli_verify_no_db_access(capsys, monkeypatch, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(tmp_path / "missing.sqlite3"))
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "pass"


def test_cli_verify_malformed_sums_line(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    sums_path = root / "export" / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    sums_path.write_text(f"{lines[0]}\nbadline\n{lines[1]}\n", encoding="utf-8")
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("Malformed SHA256SUMS line" in r for r in payload["reasons"])


def test_cli_verify_unsupported_sums_entry(capsys, tmp_path):
    root = tmp_path / "evidence"
    _write_valid_evidence_dir(root / "v1.10.0")
    exporter.export_release_evidence_index(
        evidence_root=root,
        output_dir=root / "export",
        fmt="both",
    )
    sums_path = root / "export" / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").strip().splitlines()
    fake_hash = "a" * 64
    sums_path.write_text(f"{lines[0]}\n{fake_hash}  extra.txt\n{lines[1]}\n", encoding="utf-8")
    (root / "export" / "extra.txt").write_text("extra", encoding="utf-8")
    result = main([
        "release-evidence-index-export-verify",
        "--export-dir", str(root / "export"),
    ])
    assert result != 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["status"] == "fail"
    assert any("Unsupported artifact" in r for r in payload["reasons"])
