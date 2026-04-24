from pathlib import Path

from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db


def test_export_repository_persists_precision_and_report_scaffold(tmp_path):
    db_path = tmp_path / "exports.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id="run-001",
        manifest_path="data/manifests/manifest-hash-001.json",
    )

    repository = ExportRepository(db_path, export_root=tmp_path)
    candidates = [
        {
            "candidate_id": "candidate-002",
            "centroid": [1234.0, 2789.0],
            "bounds": [1201.0, 2705.0, 1281.0, 2879.0],
            "area_m2": 9600.0,
            "possible_duplicate": False,
        },
        {
            "candidate_id": "candidate-001",
            "centroid": [1899.0, 3151.0],
            "bounds": [1800.0, 3100.0, 1950.0, 3200.0],
            "area_m2": 12000.0,
            "possible_duplicate": True,
        },
    ]

    public_record = repository.persist_export(
        run_id="run-001",
        audience="public",
        candidates=candidates,
    )
    reviewer_record = repository.persist_export(
        run_id="run-001",
        audience="reviewer",
        candidates=candidates,
    )
    field_record = repository.persist_export(
        run_id="run-001",
        audience="field",
        candidates=candidates,
    )
    report_record = repository.persist_export(
        run_id="run-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=candidates,
    )

    records = repository.fetch_export_records("run-001")
    report_path = tmp_path / Path(report_record["artifact_path"])

    assert public_record["precision_tier"] == "coarse"
    assert public_record["exact_coordinates_included"] is False
    assert public_record["coordinate_resolution_m"] == 1000
    assert public_record["candidates"][0]["candidate_id"] == "candidate-001"
    assert public_record["candidates"][0]["centroid"] == [2000.0, 3000.0]
    assert "e2000_n3000" in public_record["artifact_name"]

    assert reviewer_record["precision_tier"] == "exact"
    assert reviewer_record["exact_coordinates_included"] is True
    assert reviewer_record["candidates"][0]["centroid"] == [1899.0, 3151.0]
    assert "e1899_n3151" in reviewer_record["artifact_name"]

    assert field_record["precision_tier"] == "exact"
    assert field_record["exact_coordinates_included"] is True
    assert field_record["candidates"][0]["centroid"] == [1899.0, 3151.0]
    assert "e1900_n3200" in field_record["bundle_name"]

    assert report_record["precision_tier"] == "restricted"
    assert report_record["exact_coordinates_included"] is False
    assert report_record["coordinate_resolution_m"] == 100
    assert report_record["artifact_path"].endswith(".md")
    assert report_path.exists()
    assert "Lawful Anomaly Screening Report" in report_path.read_text(encoding="utf-8")
    assert "`restricted`" in report_path.read_text(encoding="utf-8")

    assert [record["audience"] for record in records] == ["field", "public", "report_pdf", "reviewer"]
