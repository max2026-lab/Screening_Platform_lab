import json
from pathlib import Path
import sqlite3
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
    assert len(empty_result["files"]) == 3
    assert "calibration_artifact_registry.json" in empty_result["files"]

    # Verify JSON file matches memory
    json_path = snapshot_dir / "calibration_artifact_registry.json"
    assert json_path.exists()
    empty_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert empty_json["artifact_count"] == 0
    assert empty_json["snapshot_hash"] == empty_result["snapshot_hash"]
    
    # Add artifacts
    repo = CalibrationArtifactRepository(db_path)
    repo.save_artifact(_create_fake_artifact("hash2", "run-b", "incomplete"))
    repo.save_artifact(_create_fake_artifact("hash1", "run-a", "ready"))

    # Export again
    snapshot_dir2 = tmp_path / "snapshot_full"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir2)]) == 0
    full_result = json.loads(output.getvalue())
    assert full_result["artifact_count"] == 2
    assert full_result["snapshot_hash"] != empty_result["snapshot_hash"]

    # Verify JSON file structure and sorting
    json_path2 = snapshot_dir2 / "calibration_artifact_registry.json"
    full_json = json.loads(json_path2.read_text(encoding="utf-8"))
    assert full_json["snapshot_type"] == "calibration_artifact_registry"
    assert full_json["snapshot_version"] == 1
    assert full_json["artifact_count"] == 2
    assert full_json["artifacts"][0]["run_id"] == "run-a"
    assert full_json["artifacts"][1]["run_id"] == "run-b"

    # Export same DB to different dir has same hash
    snapshot_dir3 = tmp_path / "snapshot_full_copy"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir3)]) == 0
    copy_result = json.loads(output.getvalue())
    assert copy_result["snapshot_hash"] == full_result["snapshot_hash"]

    # Verify markdown
    md_path = snapshot_dir2 / "calibration_artifact_registry.md"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# Calibration Registry Snapshot" in md_text
    assert "Status: `exported`" in md_text
    assert f"Snapshot hash: `{full_result['snapshot_hash']}`" in md_text
    assert "## Artifacts" in md_text
    assert "`run-a`" in md_text

    # Verify SHA256SUMS
    sums_path = snapshot_dir2 / "SHA256SUMS.txt"
    sums_text = sums_path.read_text(encoding="utf-8")
    assert "calibration_artifact_registry.json" in sums_text
    assert "calibration_artifact_registry.md" in sums_text
    assert "SHA256SUMS.txt" not in sums_text
    
    actual_json_hash = hashlib.sha256(json_path2.read_bytes()).hexdigest()
    assert actual_json_hash in sums_text
    
    # Test --output markdown
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-registry-export", "--output-dir", str(snapshot_dir3), "--output", "markdown"]) == 0
    md_out = output.getvalue()
    assert md_out == md_text
