import json
from pathlib import Path

from lawful_anomaly_screening.db.repositories.manifest_repository import ManifestRepository
from lawful_anomaly_screening.db.sqlite import init_db
from lawful_anomaly_screening.sources.manifest_builder import build_manifest


def test_manifest_repository_persists_manifest_and_reference(tmp_path):
    db_path = tmp_path / "manifest.sqlite3"
    manifest_root = tmp_path / "manifests"
    init_db(db_path)

    repository = ManifestRepository(db_path, manifest_root=manifest_root)
    manifest = build_manifest("cdse")
    record = repository.persist_manifest(manifest)
    stored_row = repository.fetch_manifest_row(record["source_scene_manifest_hash"])

    assert stored_row is not None
    assert stored_row["source_endpoint_id"] == "cdse"
    assert stored_row["source_name"] == "cdse"
    assert Path(record["manifest_path"]).is_file()
    payload = json.loads(Path(record["manifest_path"]).read_text(encoding="utf-8"))
    assert payload["source_endpoint_id"] == "cdse"
