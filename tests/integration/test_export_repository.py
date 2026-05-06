import hashlib
import json
from pathlib import Path
import zipfile

from lawful_anomaly_screening.cli import main
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
    assert public_record["audit_manifest"]["precision_tier"] == "coarse"
    assert public_record["audit_manifest"]["exact_coordinates_included"] is False
    assert public_record["audit_manifest"]["coordinate_resolution_m"] == 1000
    assert public_record["audit_manifest"]["artifact_name_resolution_m"] == 1000
    assert public_record["audit_manifest"]["processing_baseline_id"] == "baseline_v1_5_default"
    assert public_record["audit_manifest"]["score_formula_version"] == "v1.5.1-phase0"
    assert public_record["audit_manifest"]["source_endpoint_id"] == "earth_search"
    assert public_record["audit_manifest"]["source_scene_manifest_hash"] == "manifest-hash-001"
    assert public_record["audit_manifest"]["legal_gate"]["decision"] == "fail"
    assert public_record["audit_manifest"]["candidate_count"] == 2
    assert public_record["audit_manifest"]["candidate_ids"] == ["candidate-001", "candidate-002"]
    assert public_record["audit_manifest"]["top_candidate_id"] == "candidate-002"
    assert public_record["audit_manifest"]["candidate_score_formula_versions"] == []
    assert public_record["audit_manifest"]["audit_manifest_hash"]
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
    assert report_record["audit_manifest"]["precision_tier"] == "restricted"
    assert report_record["audit_manifest"]["coordinate_resolution_m"] == 100
    assert report_record["audit_manifest"]["artifact_name_resolution_m"] == 100
    assert report_record["audit_manifest"]["candidate_ids"] == ["candidate-001", "candidate-002"]
    assert report_record["audit_manifest"]["candidate_count"] == 2
    assert report_record["audit_manifest"]["top_candidate_id"] == "candidate-002"
    assert report_record["artifact_path"].endswith(".md")
    assert report_path.exists()
    assert "Lawful Anomaly Screening Report" in report_path.read_text(encoding="utf-8")
    assert "`restricted`" in report_path.read_text(encoding="utf-8")

    assert report_record["bundle_path"] is not None
    assert report_record["bundle_path"].endswith(".zip")
    bundle_path = tmp_path / Path(report_record["bundle_path"])
    assert bundle_path.exists()
    assert bundle_path.name == report_record["bundle_name"]
    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = sorted(zf.namelist())
        assert names == sorted([
            report_record["artifact_name"],
            "audit_manifest.json",
            "SHA256SUMS.txt",
        ])
        zip_report = zf.read(report_record["artifact_name"]).decode("utf-8")
        assert zip_report == report_path.read_text(encoding="utf-8")
        zip_manifest = json.loads(zf.read("audit_manifest.json").decode("utf-8"))
        assert zip_manifest == report_record["audit_manifest"]
        sha256sums = zf.read("SHA256SUMS.txt").decode("utf-8")
        report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(
            json.dumps(report_record["audit_manifest"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert f"{report_hash}  {report_record['artifact_name']}" in sha256sums
        assert f"{manifest_hash}  audit_manifest.json" in sha256sums

    assert report_record["bundle_manifest_path"] is not None
    assert report_record["bundle_manifest_path"].endswith(".manifest.json")
    manifest_path = tmp_path / Path(report_record["bundle_manifest_path"])
    assert manifest_path.exists()
    assert manifest_path.name == f"{report_record['bundle_name']}.manifest.json"
    sidecar = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "v1.7_report_bundle_manifest"
    assert sidecar["run_id"] == "run-001"
    assert sidecar["export_record_id"] == report_record["export_record_id"]
    assert sidecar["audience"] == "report_pdf"
    assert sidecar["precision_tier"] == "restricted"
    assert sidecar["exact_coordinates_included"] is False
    assert sidecar["coordinate_resolution_m"] == 100
    assert sidecar["artifact_name"] == report_record["artifact_name"]
    assert sidecar["artifact_path"] == report_record["artifact_path"]
    assert sidecar["bundle_name"] == report_record["bundle_name"]
    assert sidecar["bundle_path"] == report_record["bundle_path"]
    assert sidecar["bundle_sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert sidecar["bundle_members"] == sorted([
        report_record["artifact_name"],
        "audit_manifest.json",
        "SHA256SUMS.txt",
    ])
    assert sidecar["audit_manifest_hash"] == report_record["audit_manifest"]["audit_manifest_hash"]
    assert sidecar["source_endpoint_id"] == "earth_search"
    assert sidecar["source_scene_manifest_hash"] == "manifest-hash-001"
    assert sidecar["candidate_count"] == 2
    assert len(sidecar["files"]) == 4
    file_names = [f["name"] for f in sidecar["files"]]
    assert report_record["artifact_name"] in file_names
    assert report_record["bundle_name"] in file_names
    assert "audit_manifest.json" in file_names
    assert "SHA256SUMS.txt" in file_names
    report_file_entry = next(f for f in sidecar["files"] if f["name"] == report_record["artifact_name"])
    assert report_file_entry["kind"] == "report_markdown"
    assert report_file_entry["sha256"] == report_hash
    assert report_file_entry["path"] == report_record["artifact_path"]
    bundle_file_entry = next(f for f in sidecar["files"] if f["name"] == report_record["bundle_name"])
    assert bundle_file_entry["kind"] == "bundle_zip"
    assert bundle_file_entry["sha256"] == sidecar["bundle_sha256"]
    assert bundle_file_entry["path"] == report_record["bundle_path"]
    audit_entry = next(f for f in sidecar["files"] if f["name"] == "audit_manifest.json")
    assert audit_entry["kind"] == "audit_manifest"
    assert audit_entry["sha256"] == manifest_hash
    assert audit_entry["zip_member"] is True
    sha_entry = next(f for f in sidecar["files"] if f["name"] == "SHA256SUMS.txt")
    assert sha_entry["kind"] == "checksum_manifest"
    assert sha_entry["sha256"] == hashlib.sha256(sha256sums.encode("utf-8")).hexdigest()
    assert sha_entry["zip_member"] is True
    assert "centroid" not in str(sidecar).lower()

    assert [record["audience"] for record in records] == ["field", "public", "report_pdf", "reviewer"]
    repeated_report_record = repository.persist_export(
        run_id="run-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=candidates,
    )
    assert repeated_report_record["audit_manifest"]["candidate_ids"] == report_record["audit_manifest"]["candidate_ids"]
    assert repeated_report_record["audit_manifest"]["audit_manifest_hash"] == (
        report_record["audit_manifest"]["audit_manifest_hash"]
    )
    assert repeated_report_record["bundle_name"] == report_record["bundle_name"]
    assert repeated_report_record["bundle_path"] == report_record["bundle_path"]
    assert repeated_report_record["bundle_manifest_path"] == report_record["bundle_manifest_path"]
    repeated_sidecar = json.loads((tmp_path / Path(repeated_report_record["bundle_manifest_path"])).read_text(encoding="utf-8"))
    assert repeated_sidecar["bundle_sha256"] == sidecar["bundle_sha256"]
    assert repeated_sidecar["audit_manifest_hash"] == sidecar["audit_manifest_hash"]
    assert repeated_sidecar["files"] == sidecar["files"]


def test_zero_candidate_report_export_restricted(tmp_path):
    db_path = tmp_path / "zero_exports.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-002",
        source_endpoint_id="earth_search",
        run_id="run-002",
        manifest_path="data/manifests/manifest-hash-002.json",
        run_status="completed",
        aoi_hash="aoi-hash-002",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate={
            "attestation_status": "present",
            "geofence_status": "clear",
            "decision": "pass",
            "reason": "",
            "evaluated_at": "2024-01-01T00:00:00Z",
        },
    )

    repository = ExportRepository(db_path, export_root=tmp_path)
    export_record = repository.persist_export(
        run_id="run-002",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=[],
    )

    assert export_record["precision_tier"] == "restricted"
    assert export_record["exact_coordinates_included"] is False
    assert export_record["candidates"] == []
    assert export_record["audit_manifest"]["candidate_count"] == 0
    assert export_record["audit_manifest"]["candidate_ids"] == []
    assert export_record["audit_manifest"]["top_candidate_id"] is None
    assert export_record["artifact_path"].endswith(".md")

    report_path = tmp_path / Path(export_record["artifact_path"])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Lawful Anomaly Screening Report" in report_text
    assert "Candidate count: `0`" in report_text
    assert "## No Exportable Candidates Found" in report_text
    assert "This AOI/date window was screened and produced zero exportable candidates." in report_text
    assert "AOI hash: `aoi-hash-002`" in report_text
    assert "Start date: `2024-01-01`" in report_text
    assert "End date: `2024-03-31`" in report_text
    assert "Legal gate decision: `pass`" in report_text
    assert "centroid" not in report_text.lower()

    assert export_record["bundle_path"] is not None
    bundle_path = tmp_path / Path(export_record["bundle_path"])
    assert bundle_path.exists()
    assert bundle_path.name == export_record["bundle_name"]
    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = sorted(zf.namelist())
        assert names == sorted([
            export_record["artifact_name"],
            "audit_manifest.json",
            "SHA256SUMS.txt",
        ])
        zip_report = zf.read(export_record["artifact_name"]).decode("utf-8")
        assert zip_report == report_text
        zip_manifest = json.loads(zf.read("audit_manifest.json").decode("utf-8"))
        assert zip_manifest == export_record["audit_manifest"]
        sha256sums = zf.read("SHA256SUMS.txt").decode("utf-8")
        report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(
            json.dumps(export_record["audit_manifest"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert f"{report_hash}  {export_record['artifact_name']}" in sha256sums
        assert f"{manifest_hash}  audit_manifest.json" in sha256sums

    assert export_record["bundle_manifest_path"] is not None
    manifest_path = tmp_path / Path(export_record["bundle_manifest_path"])
    assert manifest_path.exists()
    assert manifest_path.name == f"{export_record['bundle_name']}.manifest.json"
    sidecar = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == "v1.7_report_bundle_manifest"
    assert sidecar["candidate_count"] == 0
    assert sidecar["audit_manifest_hash"] == export_record["audit_manifest"]["audit_manifest_hash"]
    assert "centroid" not in str(sidecar).lower()
    assert sidecar["bundle_sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    assert sidecar["bundle_members"] == sorted([
        export_record["artifact_name"],
        "audit_manifest.json",
        "SHA256SUMS.txt",
    ])


def test_export_create_fails_for_invalid_run_id(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "invalid_run.sqlite3"
    init_db(db_path)
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    result = main([
        "export-create",
        "--run-id", "nonexistent-run",
        "--audience", "public",
    ])
    assert result == 1
    captured = capsys.readouterr()
    assert "no export candidates found for run: nonexistent-run" in captured.err


def test_export_create_zero_candidates_report_pdf_restricted(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "zero_cli.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-003",
        source_endpoint_id="earth_search",
        run_id="run-003",
        manifest_path="data/manifests/manifest-hash-003.json",
        run_status="completed",
        aoi_hash="aoi-hash-003",
        start_date="2024-06-01",
        end_date="2024-06-30",
        legal_gate={
            "attestation_status": "present",
            "geofence_status": "clear",
            "decision": "pass",
            "reason": "",
            "evaluated_at": "2024-06-01T00:00:00Z",
        },
    )
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    monkeypatch.chdir(tmp_path)

    result = main([
        "export-create",
        "--run-id", "run-003",
        "--audience", "report_pdf",
        "--requested-precision", "restricted",
    ])
    assert result == 0

    stdout_text = capsys.readouterr().out
    export_payload = json.loads(stdout_text)
    assert export_payload["candidates"] == []
    assert export_payload["audit_manifest"]
    assert export_payload["artifact_path"].endswith(".md")
    assert export_payload["exact_coordinates_included"] is False

    report_path = tmp_path / Path(export_payload["artifact_path"])
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Candidate count: `0`" in report_text
    assert "## No Exportable Candidates Found" in report_text
    assert "This AOI/date window was screened and produced zero exportable candidates." in report_text
    assert "centroid" not in report_text.lower()


def test_non_report_audiences_do_not_create_bundles(tmp_path):
    db_path = tmp_path / "non_report.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-005",
        source_endpoint_id="earth_search",
        run_id="run-005",
        manifest_path="data/manifests/manifest-hash-005.json",
    )

    repository = ExportRepository(db_path, export_root=tmp_path)
    candidates = [
        {
            "candidate_id": "candidate-001",
            "centroid": [1234.0, 2789.0],
            "bounds": [1201.0, 2705.0, 1281.0, 2879.0],
            "area_m2": 9600.0,
            "possible_duplicate": False,
        },
    ]

    public_record = repository.persist_export(
        run_id="run-005",
        audience="public",
        candidates=candidates,
    )
    reviewer_record = repository.persist_export(
        run_id="run-005",
        audience="reviewer",
        candidates=candidates,
    )
    field_record = repository.persist_export(
        run_id="run-005",
        audience="field",
        candidates=candidates,
    )

    assert public_record["bundle_path"] is None
    assert reviewer_record["bundle_path"] is None
    assert field_record["bundle_path"] is None
    assert public_record["bundle_manifest_path"] is None
    assert reviewer_record["bundle_manifest_path"] is None
    assert field_record["bundle_manifest_path"] is None

    reports_dir = tmp_path / "exports" / "reports"
    assert not reports_dir.exists() or not any(reports_dir.rglob("*.zip"))
    assert not reports_dir.exists() or not any(reports_dir.rglob("*.manifest.json"))


def test_export_create_zero_candidates_fails_for_public_audience(monkeypatch, capsys, tmp_path):
    db_path = tmp_path / "zero_public.sqlite3"
    init_db(db_path)
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-004",
        source_endpoint_id="earth_search",
        run_id="run-004",
        manifest_path="data/manifests/manifest-hash-004.json",
        run_status="completed",
        aoi_hash="aoi-hash-004",
        start_date="2024-07-01",
        end_date="2024-07-31",
        legal_gate={
            "attestation_status": "present",
            "geofence_status": "clear",
            "decision": "pass",
            "reason": "",
            "evaluated_at": "2024-07-01T00:00:00Z",
        },
    )
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))

    result = main([
        "export-create",
        "--run-id", "run-004",
        "--audience", "public",
    ])
    assert result != 0
    captured = capsys.readouterr()
    assert "no export candidates found for run: run-004" in captured.err
    assert not (tmp_path / "exports" / "public").exists() or not any(
        (tmp_path / "exports" / "public").rglob("*.json")
    )
