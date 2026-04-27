import json
import re
from pathlib import Path
import io
import hashlib
from contextlib import redirect_stdout, redirect_stderr

import pytest

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.sqlite import init_db
from lawful_anomaly_screening.db.repositories.calibration_artifact_repository import CalibrationArtifactRepository

def _create_fake_artifact(artifact_hash: str, run_id: str, status: str = "ready") -> dict:
    return {
        "artifact_hash": artifact_hash,
        "run_id": run_id,
        "artifact_status": status,
        "label_pack_hash": f"pack_{artifact_hash}",
        "label_manifest_hash": f"manifest_{artifact_hash}",
        "label_count": 10,
        "include_pending": False,
        "files": ["calibration_label_pack.json", "calibration_label_manifest.json", "calibration_label_manifest.md", "SHA256SUMS.txt"],
        "file_hashes": {
            "calibration_label_pack.json": f"hash_pack_{artifact_hash}",
            "calibration_label_manifest.json": f"hash_manifest_{artifact_hash}",
            "calibration_label_manifest.md": f"hash_md_{artifact_hash}",
            "SHA256SUMS.txt": f"hash_sums_{artifact_hash}",
        },
        "verification": {"status": "valid", "reasons": []},
    }

def _recompute_sha256sums(evidence_dir: Path) -> None:
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    md_path = evidence_dir / "calibration_registry_snapshot_diff.md"
    json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    sums_text = f"{json_hash}  calibration_registry_snapshot_diff.json\n{md_hash}  calibration_registry_snapshot_diff.md\n"
    (evidence_dir / "SHA256SUMS.txt").write_text(sums_text, encoding="utf-8", newline="\n")

def test_calibration_registry_snapshot_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    # Empty registry export
    snapshot_dir = tmp_path / "snapshot_empty"
    
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0
    empty_result = json.loads(output.getvalue())
    assert empty_result["status"] == "exported"
    assert empty_result["artifact_count"] == 0
    assert empty_result["snapshot_hash"] is not None
    
    # Add artifacts
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    # Export again
    snapshot_dir2 = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir2)]) == 0
    full_result = json.loads(output.getvalue())

    # Check required command JSON fields
    expected_fields = {"status", "reasons", "output_dir", "artifact_count", "snapshot_hash", "files", "file_hashes"}
    assert expected_fields.issubset(full_result.keys())

    assert full_result["status"] == "exported"
    assert full_result["artifact_count"] == 3
    assert full_result["snapshot_hash"] != empty_result["snapshot_hash"]

    # Files list exact match
    expected_files = [
        "calibration_artifact_registry.json",
        "calibration_artifact_registry.md",
        "SHA256SUMS.txt",
    ]
    assert full_result["files"] == expected_files
    assert full_result["output_dir"] == str(snapshot_dir2)

    # Verify JSON file matches memory
    json_path2 = snapshot_dir2 / "calibration_artifact_registry.json"
    md_path = snapshot_dir2 / "calibration_artifact_registry.md"
    sums_path = snapshot_dir2 / "SHA256SUMS.txt"

    # All three files exist and are UTF-8 readable
    assert json_path2.exists()
    assert md_path.exists()
    assert sums_path.exists()

    json_text = json_path2.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")
    sums_text = sums_path.read_text(encoding="utf-8")

    full_json = json.loads(json_text)
    assert full_json["snapshot_type"] == "calibration_artifact_registry"
    assert full_json["snapshot_version"] == 1
    assert full_json["artifact_count"] == 3
    assert full_json["snapshot_hash"] == full_result["snapshot_hash"]
    
    # Artifact entries are sorted by run_id then artifact_hash
    assert full_json["artifacts"][0]["run_id"] == "run-a"
    assert full_json["artifacts"][1]["run_id"] == "run-b"
    assert full_json["artifacts"][2]["run_id"] == "run-c"

    # Exported artifact statuses include ready, incomplete, and fail
    statuses = {a["artifact_status"] for a in full_json["artifacts"]}
    assert statuses == {"ready", "incomplete", "fail"}

    # Exported snapshot JSON contains no full label payload fields
    json_str = json.dumps(full_json)
    assert "labels" not in full_json
    assert "label_ids" not in full_json
    
    # Exported snapshot JSON contains no coordinate fields
    for coord_field in ["lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox"]:
        assert f'"{coord_field}"' not in json_str

    # Command JSON file_hashes match actual file contents
    actual_json_hash = hashlib.sha256(json_path2.read_bytes()).hexdigest()
    actual_md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    actual_sums_hash = hashlib.sha256(sums_path.read_bytes()).hexdigest()

    assert full_result["file_hashes"]["calibration_artifact_registry.json"] == actual_json_hash
    assert full_result["file_hashes"]["calibration_artifact_registry.md"] == actual_md_hash
    assert full_result["file_hashes"]["SHA256SUMS.txt"] == actual_sums_hash

    # SHA256SUMS contains correct hashes
    assert f"{actual_json_hash}  calibration_artifact_registry.json" in sums_text
    assert f"{actual_md_hash}  calibration_artifact_registry.md" in sums_text
    
    # SHA256SUMS does not include self hash line
    assert "SHA256SUMS.txt" not in sums_text

    # Snapshot hash is identical across different output directories for the same DB state
    snapshot_dir3 = tmp_path / "snapshot_full_copy"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir3)]) == 0
    copy_result = json.loads(output.getvalue())
    assert copy_result["snapshot_hash"] == full_result["snapshot_hash"]

    # Snapshot hash is deterministic across repeated exports to the same directory
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir2)]) == 0
    repeat_result = json.loads(output.getvalue())
    assert repeat_result["snapshot_hash"] == full_result["snapshot_hash"]
    
    # Adding one additional registered artifact changes snapshot_hash
    repo.save_artifact(_create_fake_artifact("hash4", "run-d", "ready"))
    snapshot_dir4 = tmp_path / "snapshot_plus_one"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir4)]) == 0
    plus_one_result = json.loads(output.getvalue())
    assert plus_one_result["snapshot_hash"] != full_result["snapshot_hash"]

    # Verify markdown
    assert "# Calibration Registry Snapshot" in md_text
    assert f"- Snapshot hash: `{full_result['snapshot_hash']}`" in md_text
    assert "- Artifact count: `3`" in md_text
    assert "## Files" in md_text
    assert "## Reasons" in md_text
    assert "## Artifacts" in md_text


def test_calibration_registry_snapshot_verify_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    snapshot_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    # Verify without DB access
    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "valid"
    assert result["artifact_count"] == 0
    assert result["snapshot_hash"] is not None
    assert result["sha256sums_valid"] is True
    assert result["snapshot_hash_valid"] is True
    assert result["snapshot_cross_checks_valid"] is True
    expected_fields = {
        "status", "reasons", "snapshot_dir", "artifact_count", "snapshot_hash",
        "files", "file_hashes", "sha256sums_valid", "snapshot_hash_valid", "snapshot_cross_checks_valid",
    }
    assert expected_fields.issubset(result.keys())


def test_calibration_registry_snapshot_verify_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    snapshot_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "valid"
    assert result["artifact_count"] == 3
    assert result["sha256sums_valid"] is True
    assert result["snapshot_hash_valid"] is True
    assert result["snapshot_cross_checks_valid"] is True


def test_calibration_registry_snapshot_verify_markdown_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    snapshot_dir = tmp_path / "snapshot_md"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir), "--output", "markdown"]) == 0
    md_text = output.getvalue()

    assert "# Calibration Registry Snapshot Verification" in md_text
    assert "- Status: `valid`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_verify_tampered_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_tamper"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"


def test_calibration_registry_snapshot_verify_tampered_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_tamper_md"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    md_path = snapshot_dir / "calibration_artifact_registry.md"
    md_text = md_path.read_text(encoding="utf-8")
    md_path.write_text(md_text.replace("Calibration Registry Snapshot", "TAMPERED"), encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"


def test_calibration_registry_snapshot_verify_tampered_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_tamper_sums"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    sums_path = snapshot_dir / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    sums_path.write_text(sums_text.replace("0", "1"), encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["sha256sums_valid"] is False


def test_calibration_registry_snapshot_verify_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_missing"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    (snapshot_dir / "SHA256SUMS.txt").unlink()

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"


def test_calibration_registry_snapshot_verify_unsorted_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "ready"))

    snapshot_dir = tmp_path / "snapshot_unsorted"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"] = list(reversed(data["artifacts"]))
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("sorted" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_artifact_count_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_count"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 99
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("artifact_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_coordinate_field_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_coord"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"][0]["lon"] = 1.0
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("coordinate" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_label_payload_field_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_labels"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"][0]["labels"] = []
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("label payload" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_malformed_artifacts_not_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_bad_artifacts"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"] = "bad"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("artifacts must be a list" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_malformed_artifact_entry_not_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_bad_entry"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"] = ["bad"]
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("JSON object" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_artifact_count_non_integer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_bad_count"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = "99"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("artifact_count must be an integer" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_tampered_md_recomputed_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_tamper_md_recomputed"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    # Tamper markdown but keep snapshot hash line intact
    md_path = snapshot_dir / "calibration_artifact_registry.md"
    md_text = md_path.read_text(encoding="utf-8")
    tampered_md = md_text.replace("Registry snapshot exported successfully", "TAMPERED SUCCESS")
    md_path.write_text(tampered_md, encoding="utf-8")

    # Recompute SHA256SUMS to match tampered markdown
    from hashlib import sha256
    new_md_hash = sha256(tampered_md.encode("utf-8")).hexdigest()
    json_path = snapshot_dir / "calibration_artifact_registry.json"
    json_text = json_path.read_text(encoding="utf-8")
    json_hash = sha256(json_text.encode("utf-8")).hexdigest()
    new_sums = f"{json_hash}  calibration_artifact_registry.json\n{new_md_hash}  calibration_artifact_registry.md\n"
    (snapshot_dir / "SHA256SUMS.txt").write_text(new_sums, encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir)]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("canonical final content" in r for r in result["reasons"])


def test_calibration_registry_snapshot_verify_markdown_output_malformed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot_md_malformed"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    json_path = snapshot_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifacts"] = "bad"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-verify", "--snapshot-dir", str(snapshot_dir), "--output", "markdown"]) == 1
    md_text = output.getvalue()

    assert "# Calibration Registry Snapshot Verification" in md_text
    assert "- Status: `invalid`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_empty_vs_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_empty_before"
    after_dir = tmp_path / "snapshot_empty_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["before_artifact_count"] == 0
    assert result["after_artifact_count"] == 0
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0
    assert result["diff_hash"] is not None
    assert result["before_valid"] is True
    assert result["after_valid"] is True


def test_calibration_registry_snapshot_diff_empty_vs_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_empty"
    after_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 1
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0
    assert result["added"][0]["artifact_hash"] == "hash1"


def test_calibration_registry_snapshot_diff_full_vs_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    empty_db_path = tmp_path / "empty_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(empty_db_path))
    init_db(empty_db_path)

    after_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 0
    assert result["removed_count"] == 1
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0
    assert result["removed"][0]["artifact_hash"] == "hash1"


def test_calibration_registry_snapshot_diff_same_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    snapshot_dir = tmp_path / "snapshot"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(snapshot_dir), "--after-snapshot-dir", str(snapshot_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 1
    assert result["unchanged"][0]["artifact_hash"] == "hash1"


def test_calibration_registry_snapshot_diff_same_snapshot_different_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 1
    assert result["diff_hash"] is not None


def test_calibration_registry_snapshot_diff_one_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "ready"))
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 1
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 1
    assert result["added"][0]["artifact_hash"] == "hash2"


def test_calibration_registry_snapshot_diff_tampered_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    json_path = before_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 1
    result = json.loads(output.getvalue())

    assert result["status"] == "invalid"
    assert result["before_valid"] is False
    assert result["after_valid"] is True


def test_calibration_registry_snapshot_diff_tampered_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    json_path = after_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 1
    result = json.loads(output.getvalue())

    assert result["status"] == "invalid"
    assert result["before_valid"] is True
    assert result["after_valid"] is False


def test_calibration_registry_snapshot_diff_markdown_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir), "--output", "markdown"]) == 0
    md_text = output.getvalue()

    assert "# Calibration Registry Snapshot Diff" in md_text
    assert "- Status: `compared`" in md_text
    assert "- Diff hash:" in md_text
    assert "- Before snapshot hash:" in md_text
    assert "- After snapshot hash:" in md_text
    assert "## Reasons" in md_text
    assert "## Added Artifacts" in md_text
    assert "## Removed Artifacts" in md_text
    assert "## Changed Artifacts" in md_text
    assert "## Unchanged Artifacts" in md_text


def test_calibration_registry_snapshot_diff_no_label_payload_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    result_str = json.dumps(result)
    assert '"labels"' not in result_str
    assert '"label_ids"' not in result_str


def test_calibration_registry_snapshot_diff_no_coordinate_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    result_str = json.dumps(result)
    for field in ["lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox"]:
        assert f'"{field}"' not in result_str


def test_calibration_registry_snapshot_diff_required_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    required_fields = {
        "status", "reasons", "before_snapshot_dir", "after_snapshot_dir",
        "before_snapshot_hash", "after_snapshot_hash", "before_artifact_count",
        "after_artifact_count", "added_count", "removed_count", "changed_count",
        "unchanged_count", "diff_hash", "added", "removed", "changed", "unchanged",
        "before_valid", "after_valid",
    }
    assert required_fields.issubset(result.keys())


def test_calibration_registry_snapshot_diff_changed_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)

    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 1
    assert result["unchanged_count"] == 0

    changed_row = result["changed"][0]
    assert changed_row["artifact_hash"] == "hash1"

    before_expected_fields = {
        "run_id", "artifact_status", "label_pack_hash", "label_manifest_hash",
        "label_count", "include_pending", "files", "file_hashes",
    }
    assert before_expected_fields.issubset(changed_row["before"].keys())
    assert before_expected_fields.issubset(changed_row["after"].keys())

    assert changed_row["before"]["label_count"] == 10
    assert changed_row["after"]["label_count"] == 20
    assert changed_row["changed_fields"] == sorted(changed_row["changed_fields"])
    assert "label_count" in changed_row["changed_fields"]


def test_calibration_registry_snapshot_diff_hash_deterministic_across_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    copied_before = tmp_path / "copied_before"
    copied_after = tmp_path / "copied_after"
    import shutil
    shutil.copytree(before_dir, copied_before)
    shutil.copytree(after_dir, copied_after)

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result1 = json.loads(output.getvalue())

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(copied_before), "--after-snapshot-dir", str(copied_after)]) == 0
    result2 = json.loads(output.getvalue())

    assert result1["diff_hash"] == result2["diff_hash"]
    assert result1["before_snapshot_dir"] != result2["before_snapshot_dir"]
    assert result1["after_snapshot_dir"] != result2["after_snapshot_dir"]


def test_calibration_registry_snapshot_diff_hash_changes_with_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    same_as_before_dir = tmp_path / "snapshot_same"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(same_as_before_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(same_as_before_dir)]) == 0
    baseline_result = json.loads(output.getvalue())
    assert baseline_result["status"] == "compared"
    assert baseline_result["added_count"] == 0

    # Now add an artifact and create a new after snapshot
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "ready"))
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    new_result = json.loads(output.getvalue())

    assert new_result["status"] == "compared"
    assert new_result["added_count"] == 1
    assert new_result["added"][0]["artifact_hash"] == "hash2"
    assert new_result["diff_hash"] != baseline_result["diff_hash"]


def test_calibration_registry_snapshot_diff_empty_vs_empty_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_empty_before"
    after_dir = tmp_path / "snapshot_empty_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result1 = json.loads(output.getvalue())

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-snapshot-diff", "--before-snapshot-dir", str(before_dir), "--after-snapshot-dir", str(after_dir)]) == 0
    result2 = json.loads(output.getvalue())

    assert result1["diff_hash"] == result2["diff_hash"]
    assert result1["diff_hash"] is not None


def test_calibration_registry_snapshot_diff_export_empty_vs_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_empty_before"
    after_dir = tmp_path / "snapshot_empty_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["before_artifact_count"] == 0
    assert result["after_artifact_count"] == 0
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0
    assert result["diff_hash"] is not None
    assert result["output_dir"] == str(output_dir)
    assert result["before_snapshot_dir"] == str(before_dir)
    assert result["after_snapshot_dir"] == str(after_dir)

    json_path = output_dir / "calibration_registry_snapshot_diff.json"
    md_path = output_dir / "calibration_registry_snapshot_diff.md"
    sums_path = output_dir / "SHA256SUMS.txt"
    assert json_path.exists()
    assert md_path.exists()
    assert sums_path.exists()

    evidence_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert evidence_json["snapshot_diff_type"] == "calibration_registry_snapshot_diff"
    assert evidence_json["snapshot_diff_version"] == 1
    assert evidence_json["status"] == "compared"
    assert evidence_json["diff_hash"] == result["diff_hash"]
    assert set(evidence_json["file_hashes"].keys()) == {
        "calibration_registry_snapshot_diff.json",
        "calibration_registry_snapshot_diff.md",
        "SHA256SUMS.txt",
    }

    actual_json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    actual_md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    actual_sums_hash = hashlib.sha256(sums_path.read_bytes()).hexdigest()
    assert result["file_hashes"]["calibration_registry_snapshot_diff.json"] == actual_json_hash
    assert result["file_hashes"]["calibration_registry_snapshot_diff.md"] == actual_md_hash
    assert result["file_hashes"]["SHA256SUMS.txt"] == actual_sums_hash

    sums_text = sums_path.read_text(encoding="utf-8")
    assert f"{actual_json_hash}  calibration_registry_snapshot_diff.json" in sums_text
    assert f"{actual_md_hash}  calibration_registry_snapshot_diff.md" in sums_text
    assert "SHA256SUMS.txt" not in sums_text


def test_calibration_registry_snapshot_diff_export_full_vs_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    before_dir = tmp_path / "snapshot_full"
    after_dir = tmp_path / "snapshot_full2"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["unchanged_count"] == 3
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0


def test_calibration_registry_snapshot_diff_export_empty_vs_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_empty"
    after_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 1
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0


def test_calibration_registry_snapshot_diff_export_full_vs_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    empty_db_path = tmp_path / "empty_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(empty_db_path))
    init_db(empty_db_path)

    after_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert result["added_count"] == 0
    assert result["removed_count"] == 1
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 0


def test_calibration_registry_snapshot_diff_export_plus_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "ready"))
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)

    # Full-vs-full baseline using copied snapshot (offline, no DB needed)
    same_as_before = tmp_path / "snapshot_same"
    import shutil
    shutil.copytree(before_dir, same_as_before)

    baseline_dir = tmp_path / "diff_baseline"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(same_as_before),
            "--output-dir", str(baseline_dir),
        ]) == 0
    baseline_result = json.loads(output.getvalue())
    assert baseline_result["added_count"] == 0
    assert baseline_result["removed_count"] == 0
    assert baseline_result["changed_count"] == 0
    assert baseline_result["unchanged_count"] == 1

    plus_one_dir = tmp_path / "diff_plus_one"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(plus_one_dir),
        ]) == 0
    plus_one_result = json.loads(output.getvalue())

    assert plus_one_result["status"] == "compared"
    assert plus_one_result["added_count"] == 1
    assert plus_one_result["removed_count"] == 0
    assert plus_one_result["changed_count"] == 0
    assert plus_one_result["unchanged_count"] == 1
    assert plus_one_result["diff_hash"] != baseline_result["diff_hash"]

    evidence_json = json.loads((plus_one_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    assert evidence_json["added"][0]["artifact_hash"] == "hash2"
    assert evidence_json["added"][0]["run_id"] == "run-b"


def test_calibration_registry_snapshot_diff_export_deterministic_across_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    copied_before = tmp_path / "copied_before"
    copied_after = tmp_path / "copied_after"
    import shutil
    shutil.copytree(before_dir, copied_before)
    shutil.copytree(after_dir, copied_after)

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir1 = tmp_path / "diff_export1"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir1),
        ]) == 0
    result1 = json.loads(output.getvalue())

    output_dir2 = tmp_path / "diff_export2"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(copied_before),
            "--after-snapshot-dir", str(copied_after),
            "--output-dir", str(output_dir2),
        ]) == 0
    result2 = json.loads(output.getvalue())

    assert result1["diff_hash"] == result2["diff_hash"]
    assert result1["before_snapshot_dir"] != result2["before_snapshot_dir"]
    assert result1["after_snapshot_dir"] != result2["after_snapshot_dir"]

    # Evidence files identical except output_dir in stdout
    json1 = (output_dir1 / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8")
    json2 = (output_dir2 / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8")
    assert json1 == json2

    md1 = (output_dir1 / "calibration_registry_snapshot_diff.md").read_text(encoding="utf-8")
    md2 = (output_dir2 / "calibration_registry_snapshot_diff.md").read_text(encoding="utf-8")
    assert md1 == md2

    sums1 = (output_dir1 / "SHA256SUMS.txt").read_text(encoding="utf-8")
    sums2 = (output_dir2 / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert sums1 == sums2


def test_calibration_registry_snapshot_diff_export_nonempty_dir_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output_dir.mkdir()
    (output_dir / "unrelated.txt").write_text("keep me", encoding="utf-8")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 1
    result = json.loads(output.getvalue())

    assert result["status"] == "invalid"
    assert "not empty" in result["reasons"][0]
    assert (output_dir / "unrelated.txt").read_text(encoding="utf-8") == "keep me"
    assert not (output_dir / "calibration_registry_snapshot_diff.json").exists()


def test_calibration_registry_snapshot_diff_export_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output_dir.mkdir()
    (output_dir / "unrelated.txt").write_text("keep me", encoding="utf-8")
    (output_dir / "calibration_registry_snapshot_diff.json").write_text("old", encoding="utf-8")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
            "--overwrite",
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "compared"
    assert (output_dir / "unrelated.txt").read_text(encoding="utf-8") == "keep me"
    assert (output_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8") != "old"
    assert (output_dir / "calibration_registry_snapshot_diff.md").exists()
    assert (output_dir / "SHA256SUMS.txt").exists()


def test_calibration_registry_snapshot_diff_export_tampered_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    json_path = before_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 1
    result = json.loads(output.getvalue())

    assert result["status"] == "invalid"
    assert result["before_valid"] is False
    assert result["after_valid"] is True
    assert not output_dir.exists() or not (output_dir / "calibration_registry_snapshot_diff.json").exists()


def test_calibration_registry_snapshot_diff_export_tampered_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    json_path = after_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 1
    result = json.loads(output.getvalue())

    assert result["status"] == "invalid"
    assert result["before_valid"] is True
    assert result["after_valid"] is False
    assert not output_dir.exists() or not (output_dir / "calibration_registry_snapshot_diff.json").exists()


def test_calibration_registry_snapshot_diff_export_markdown_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
            "--output", "markdown",
        ]) == 0
    md_text = output.getvalue()

    assert "# Calibration Registry Snapshot Diff Export" in md_text
    assert "- Status: `compared`" in md_text
    assert "- Output directory:" in md_text
    assert "- Diff hash:" in md_text
    assert "## Reasons" in md_text
    assert "## Files" in md_text


def test_calibration_registry_snapshot_diff_export_invalid_markdown_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    json_path = before_dir / "calibration_artifact_registry.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["artifact_count"] = 999
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
            "--output", "markdown",
        ]) == 1
    md_text = output.getvalue()

    assert "# Calibration Registry Snapshot Diff Export" in md_text
    assert "- Status: `invalid`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_export_no_label_payload_or_coordinates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output_dir = tmp_path / "diff_export"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(output_dir),
        ]) == 0

    evidence_json = json.loads((output_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    json_str = json.dumps(evidence_json)
    assert '"labels"' not in json_str
    assert '"label_ids"' not in json_str
    for field in ["lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox"]:
        assert f'"{field}"' not in json_str

    md_text = (output_dir / "calibration_registry_snapshot_diff.md").read_text(encoding="utf-8")
    assert "labels" not in md_text
    assert "label_ids" not in md_text


def _create_evidence_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    before_dir = tmp_path / "snapshot_before"
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    return evidence_dir


def test_calibration_registry_snapshot_diff_export_verify_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())

    assert result["status"] == "valid"
    assert result["sha256sums_valid"] is True
    assert result["json_valid"] is True
    assert result["markdown_valid"] is True
    assert result["evidence_cross_checks_valid"] is True
    assert result["diff_hash"] is not None
    assert result["before_snapshot_hash"] is not None
    assert result["after_snapshot_hash"] is not None
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 3
    expected_fields = {
        "status", "reasons", "evidence_dir", "diff_hash", "before_snapshot_hash",
        "after_snapshot_hash", "added_count", "removed_count", "changed_count",
        "unchanged_count", "files", "file_hashes", "sha256sums_valid", "json_valid",
        "markdown_valid", "diff_hash_valid", "evidence_cross_checks_valid",
    }
    assert expected_fields.issubset(result.keys())


def test_calibration_registry_snapshot_diff_export_verify_offline_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "valid"


def test_calibration_registry_snapshot_diff_export_verify_missing_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("Missing" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.md").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"


def test_calibration_registry_snapshot_diff_export_verify_missing_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "SHA256SUMS.txt").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"


def test_calibration_registry_snapshot_diff_export_verify_tampered_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["diff_hash"] = "tampered"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["sha256sums_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_tampered_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    md_path = evidence_dir / "calibration_registry_snapshot_diff.md"
    md_text = md_path.read_text(encoding="utf-8")
    md_path.write_text(md_text.replace("Diff hash:", "TAMPERED hash:"), encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["sha256sums_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_tampered_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    sums_path = evidence_dir / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    sums_path.write_text(sums_text.replace("0", "1"), encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["sha256sums_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_self_hash_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    sums_path = evidence_dir / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    sums_path.write_text(sums_text + "abcd1234  SHA256SUMS.txt\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["sha256sums_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_malformed_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text("not json", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_wrong_snapshot_diff_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["snapshot_diff_type"] = "wrong"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_wrong_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["snapshot_diff_version"] = 2
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_status_not_compared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["status"] = "invalid"
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_before_valid_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["before_valid"] = False
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_after_valid_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["after_valid"] = False
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_count_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["added_count"] = 99
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False


def test_calibration_registry_snapshot_diff_export_verify_unsorted_changed_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)

    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data["changed"]) == 1
    data["changed"][0]["changed_fields"] = ["label_count", "artifact_status"]
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("sorted" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_injected_coordinate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["unchanged"][0]["lon"] = 1.0
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("coordinate" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_injected_label_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["unchanged"][0]["labels"] = []
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert any("label payload" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_markdown_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
            "--output", "markdown",
        ]) == 0
    md_text = output.getvalue()
    assert "# Calibration Registry Snapshot Diff Export Verification" in md_text
    assert "- Status: `valid`" in md_text
    assert "- Diff hash:" in md_text
    assert "## Reasons" in md_text
    assert "## Files" in md_text


def test_calibration_registry_snapshot_diff_export_verify_markdown_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
            "--output", "markdown",
        ]) == 1
    md_text = output.getvalue()
    assert "# Calibration Registry Snapshot Diff Export Verification" in md_text
    assert "- Status: `invalid`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_export_verify_tampered_diff_hash_matching_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["diff_hash"] = "tampered"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    # Recompute SHA256SUMS to match tampered JSON
    md_path = evidence_dir / "calibration_registry_snapshot_diff.md"
    md_text = md_path.read_text(encoding="utf-8")
    md_text = re.sub(r"Diff hash:\s*`[^`]+`", "Diff hash: `tampered`", md_text)
    md_path.write_text(md_text, encoding="utf-8", newline="\n")
    new_json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    new_md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    sums_text = f"{new_json_hash}  calibration_registry_snapshot_diff.json\n{new_md_hash}  calibration_registry_snapshot_diff.md\n"
    (evidence_dir / "SHA256SUMS.txt").write_text(sums_text, encoding="utf-8", newline="\n")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["diff_hash_valid"] is False
    assert result["sha256sums_valid"] is True


def test_calibration_registry_snapshot_diff_export_verify_md_diff_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    md_path = evidence_dir / "calibration_registry_snapshot_diff.md"
    md_text = md_path.read_text(encoding="utf-8")
    md_text = re.sub(r"Diff hash:\s*`[^`]+`", "Diff hash: `wronghash`", md_text)
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    # Recompute SHA256SUMS to match tampered markdown
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    new_md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    sums_text = f"{json_hash}  calibration_registry_snapshot_diff.json\n{new_md_hash}  calibration_registry_snapshot_diff.md\n"
    (evidence_dir / "SHA256SUMS.txt").write_text(sums_text, encoding="utf-8", newline="\n")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["markdown_valid"] is False
    assert any("diff_hash" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_empty_diff_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["diff_hash"] = ""
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    # Recompute SHA256SUMS
    md_path = evidence_dir / "calibration_registry_snapshot_diff.md"
    md_text = md_path.read_text(encoding="utf-8")
    md_text = re.sub(r"Diff hash:\s*`[^`]*`", "Diff hash: ``", md_text)
    md_path.write_text(md_text, encoding="utf-8", newline="\n")
    new_json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()
    new_md_hash = hashlib.sha256(md_path.read_bytes()).hexdigest()
    sums_text = f"{new_json_hash}  calibration_registry_snapshot_diff.json\n{new_md_hash}  calibration_registry_snapshot_diff.md\n"
    (evidence_dir / "SHA256SUMS.txt").write_text(sums_text, encoding="utf-8", newline="\n")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["diff_hash_valid"] is False
    assert any("diff_hash" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_added_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["added_count"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("added_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_removed_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["removed_count"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("removed_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_changed_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["changed_count"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("changed_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_unchanged_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["unchanged_count"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("unchanged_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_added_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["added"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("added" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_removed_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["removed"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("removed" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_changed_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["changed"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("changed" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_missing_unchanged_array(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    del data["unchanged"]
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("unchanged" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_non_list_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["added"] = "not_a_list"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("added must be a list" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_non_list_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["changed"] = "not_a_list"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["json_valid"] is False
    assert any("changed must be a list" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_non_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["changed"] = ["not_an_object"]
    data["changed_count"] = 1
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("Changed row 0 must be a JSON object" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_missing_artifact_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    data = json.loads((evidence_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    del data["changed"][0]["artifact_hash"]
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("artifact_hash" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_missing_before(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    data = json.loads((evidence_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    del data["changed"][0]["before"]
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("before" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_missing_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    data = json.loads((evidence_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    del data["changed"][0]["after"]
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("after" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_missing_changed_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    data = json.loads((evidence_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    del data["changed"][0]["changed_fields"]
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("changed_fields" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_verify_changed_row_changed_fields_non_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)
    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0
    data = json.loads((evidence_dir / "calibration_registry_snapshot_diff.json").read_text(encoding="utf-8"))
    data["changed"][0]["changed_fields"] = "not_a_list"
    (evidence_dir / "calibration_registry_snapshot_diff.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_cross_checks_valid"] is False
    assert any("changed_fields must be a list" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_accept_empty_vs_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "accepted"
    assert result["policy_id"] == "calibration_registry_diff_acceptance_v1"
    assert result["policy_version"] == 1
    assert result["evidence_valid"] is True
    assert result["decision_hash"] is not None
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["unchanged_count"] == 3


def test_calibration_registry_snapshot_diff_export_accept_full_vs_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "accepted"
    assert result["evidence_valid"] is True


def test_calibration_registry_snapshot_diff_export_accept_empty_vs_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    empty_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(empty_dir)]) == 0

    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    full_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(full_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(empty_dir),
            "--after-snapshot-dir", str(full_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "accepted"
    assert result["added_count"] == 3
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["evidence_valid"] is True


def test_calibration_registry_snapshot_diff_export_accept_full_vs_plus_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    full_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(full_dir)]) == 0

    # Add one more artifact
    repo2 = CalibrationArtifactRepository(db_path)
    repo2.save_artifact(_create_fake_artifact("hash4", "run-d", "ready"))
    plus_dir = tmp_path / "snapshot_plus"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(plus_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(full_dir),
            "--after-snapshot-dir", str(plus_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "accepted"
    assert result["added_count"] == 1
    assert result["removed_count"] == 0
    assert result["changed_count"] == 0
    assert result["evidence_valid"] is True


def test_calibration_registry_snapshot_diff_export_accept_full_vs_empty_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash3", "run-c", "fail"))

    full_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(full_dir)]) == 0

    empty_db_path = tmp_path / "empty_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(empty_db_path))
    init_db(empty_db_path)

    empty_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(empty_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(full_dir),
            "--after-snapshot-dir", str(empty_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "rejected"
    assert result["evidence_valid"] is True
    assert result["removed_count"] == 3
    assert any("removed_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_accept_changed_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before_db = tmp_path / "before_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(before_db))
    init_db(before_db)
    repo = CalibrationArtifactRepository(before_db)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    before_dir = tmp_path / "snapshot_before"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(before_dir)]) == 0

    after_db = tmp_path / "after_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(after_db))
    init_db(after_db)
    repo2 = CalibrationArtifactRepository(after_db)
    changed = _create_fake_artifact("hash1", "run-a", "ready")
    changed["label_count"] = 20
    repo2.save_artifact(changed)

    after_dir = tmp_path / "snapshot_after"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(after_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(before_dir),
            "--after-snapshot-dir", str(after_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "rejected"
    assert result["evidence_valid"] is True
    assert result["changed_count"] == 1
    assert any("changed_count" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_accept_invalid_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["diff_hash"] = "tampered"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False
    assert any("Evidence pack verification failed" in r for r in result["reasons"])


def test_calibration_registry_snapshot_diff_export_accept_missing_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False


def test_calibration_registry_snapshot_diff_export_accept_tampered_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["diff_hash"] = "tampered"
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False


def test_calibration_registry_snapshot_diff_export_accept_tampered_sums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    sums_path = evidence_dir / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    sums_path.write_text(sums_text.replace("0", "1"), encoding="utf-8")
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False


def test_calibration_registry_snapshot_diff_export_accept_injected_coordinate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["unchanged"][0]["lon"] = 1.0
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False


def test_calibration_registry_snapshot_diff_export_accept_injected_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    json_path = evidence_dir / "calibration_registry_snapshot_diff.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["unchanged"][0]["labels"] = []
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _recompute_sha256sums(evidence_dir)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert result["evidence_valid"] is False


def test_calibration_registry_snapshot_diff_export_accept_markdown_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
            "--output", "markdown",
        ]) == 0
    md_text = output.getvalue()
    assert "# Calibration Registry Snapshot Diff Acceptance" in md_text
    assert "- Status: `accepted`" in md_text
    assert "- Policy:" in md_text
    assert "- Decision hash:" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_export_accept_markdown_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    full_dir = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(full_dir)]) == 0

    empty_db_path = tmp_path / "empty_registry.sqlite3"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(empty_db_path))
    init_db(empty_db_path)

    empty_dir = tmp_path / "snapshot_empty"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(empty_dir)]) == 0

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    evidence_dir = tmp_path / "evidence"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export",
            "--before-snapshot-dir", str(full_dir),
            "--after-snapshot-dir", str(empty_dir),
            "--output-dir", str(evidence_dir),
        ]) == 0

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
            "--output", "markdown",
        ]) == 1
    md_text = output.getvalue()
    assert "# Calibration Registry Snapshot Diff Acceptance" in md_text
    assert "- Status: `rejected`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_export_accept_markdown_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").unlink()
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
            "--output", "markdown",
        ]) == 1
    md_text = output.getvalue()
    assert "# Calibration Registry Snapshot Diff Acceptance" in md_text
    assert "- Status: `invalid`" in md_text
    assert "## Reasons" in md_text


def test_calibration_registry_snapshot_diff_export_accept_decision_hash_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result1 = json.loads(output.getvalue())
    assert result1["status"] == "accepted"
    decision_hash1 = result1["decision_hash"]

    # Copy evidence to a new directory
    copied_dir = tmp_path / "copied_evidence"
    import shutil
    shutil.copytree(evidence_dir, copied_dir)

    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(copied_dir),
        ]) == 0
    result2 = json.loads(output.getvalue())
    assert result2["status"] == "accepted"
    assert result2["decision_hash"] == decision_hash1


def test_calibration_registry_snapshot_diff_export_accept_offline_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    output = io.StringIO()
    with redirect_stdout(output):
        assert main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ]) == 0
    result = json.loads(output.getvalue())
    assert result["status"] == "accepted"
    assert result["evidence_valid"] is True


def test_calibration_registry_snapshot_diff_export_accept_no_traceback_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_dir = _create_evidence_pack(tmp_path, monkeypatch)
    (evidence_dir / "calibration_registry_snapshot_diff.json").unlink()
    output = io.StringIO()
    err_output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(err_output):
        rc = main([
            "calibration-label-registry-snapshot-diff-export-accept",
            "--evidence-dir", str(evidence_dir),
        ])
    assert rc == 1
    result = json.loads(output.getvalue())
    assert result["status"] == "invalid"
    assert "Traceback" not in err_output.getvalue()
