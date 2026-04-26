import json
from pathlib import Path
import io
import hashlib
from contextlib import redirect_stdout

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
