import io
import json
from hashlib import sha256
from contextlib import redirect_stdout

from lawful_anomaly_screening.cli import main
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository
from lawful_anomaly_screening.db.repositories.review_repository import ReviewRepository
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db
from lawful_anomaly_screening.orchestration.scaffold_run import scaffold_run_for_run_id


def _legal_gate_pass() -> dict:
    return {
        "attestation_status": "present",
        "geofence_status": "clear",
        "decision": "pass",
        "reason": "legal gate passed",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _legal_gate_fail() -> dict:
    return {
        "attestation_status": "missing",
        "geofence_status": "clear",
        "decision": "fail",
        "reason": "attestation missing",
        "evaluated_at": "2026-04-25T00:00:00Z",
    }


def _bootstrap_scaffolded_run(db_path, cache_root, run_id: str, *, legal_gate=None) -> dict:
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id="baseline_v1_5_default",
        score_formula_version="v1.5.1-phase0",
        source_scene_manifest_hash="manifest-hash-001",
        source_endpoint_id="earth_search",
        run_id=run_id,
        manifest_path="data/manifests/manifest-hash-001.json",
        aoi_hash=f"aoi-hash-{run_id}",
        start_date="2024-01-01",
        end_date="2024-03-31",
        legal_gate=legal_gate or _legal_gate_pass(),
    )
    if (legal_gate or _legal_gate_pass())["decision"] != "pass":
        return {"run_id": run_id, "candidate_ids": []}
    return scaffold_run_for_run_id(
        db_path,
        run_id=run_id,
        cache_root=cache_root,
    )


def _file_hash(path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _stable_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def _canonical_markdown_for_artifact_hash(markdown: str) -> str:
    lines = markdown.splitlines()
    canonical_lines = []
    for line in lines:
        if line.startswith("- Artifact hash: `"):
            canonical_lines.append("- Artifact hash: `<artifact_hash_excluded_from_hash_input>`")
        else:
            canonical_lines.append(line)
    return "\n".join(canonical_lines) + "\n"


def _render_checksums(file_hashes: dict[str, str]) -> str:
    return "".join(f"{file_hashes[file_name]}  {file_name}\n" for file_name in sorted(file_hashes))


def _expected_artifact_hash(export: dict, output_dir) -> str:
    markdown = (output_dir / "calibration_label_manifest.md").read_text(encoding="utf-8")
    canonical_file_hashes = {
        "calibration_label_pack.json": _file_hash(output_dir / "calibration_label_pack.json"),
        "calibration_label_manifest.json": _file_hash(output_dir / "calibration_label_manifest.json"),
        "calibration_label_manifest.md": sha256(
            _canonical_markdown_for_artifact_hash(markdown).encode("utf-8")
        ).hexdigest(),
    }
    canonical_file_hashes["SHA256SUMS.txt"] = sha256(
        _render_checksums(canonical_file_hashes).encode("utf-8")
    ).hexdigest()
    return _stable_hash(
        {
            "run_id": export["run_id"],
            "include_pending": export["include_pending"],
            "files": [
                {"name": file_name, "sha256": canonical_file_hashes[file_name]}
                for file_name in export["files"]
            ],
        }
    )


def _export_artifact(run_id: str, output_dir, *, include_pending: bool = False):
    command = [
        "calibration-label-export",
        "--run-id",
        run_id,
        "--output-dir",
        str(output_dir),
    ]
    if include_pending:
        command.append("--include-pending")
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = main(command)
    return exit_code, json.loads(output.getvalue())


def _verify_artifact(artifact_dir, *, output: str = "json"):
    command = [
        "calibration-label-verify",
        "--artifact-dir",
        str(artifact_dir),
        "--output",
        output,
    ]
    captured = io.StringIO()
    with redirect_stdout(captured):
        exit_code = main(command)
    content = captured.getvalue()
    if output == "json":
        return exit_code, json.loads(content)
    return exit_code, content


def _rewrite_artifact_files(output_dir, pack: dict, manifest: dict, artifact_hash: str):
    pack_text = json.dumps(pack, indent=2, sort_keys=True) + "\n"
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    markdown_text = "\n".join(
        [
            "# Calibration Label Artifact Export",
            "",
            f"- Run ID: `{manifest['run_id']}`",
            f"- Status: `{manifest['status']}`",
            f"- Include pending: `{manifest['include_pending']}`",
            f"- Label count: `{manifest['label_count']}`",
            f"- Label pack hash: `{manifest['label_pack_hash']}`",
            f"- Label manifest hash: `{manifest['label_manifest_hash']}`",
            f"- Artifact hash: `{artifact_hash}`",
            "",
            "## Files",
            "",
            "- `calibration_label_pack.json`",
            "- `calibration_label_manifest.json`",
            "- `calibration_label_manifest.md`",
            "- `SHA256SUMS.txt`",
            "",
            "## Reasons",
            "",
            *[f"- {reason}" for reason in manifest["reasons"]],
            "",
        ]
    )
    file_hashes = {
        "calibration_label_pack.json": sha256(pack_text.encode("utf-8")).hexdigest(),
        "calibration_label_manifest.json": sha256(manifest_text.encode("utf-8")).hexdigest(),
        "calibration_label_manifest.md": sha256(markdown_text.encode("utf-8")).hexdigest(),
    }
    checksums_text = _render_checksums(file_hashes)
    file_hashes["SHA256SUMS.txt"] = sha256(checksums_text.encode("utf-8")).hexdigest()

    (output_dir / "calibration_label_pack.json").write_text(pack_text, encoding="utf-8", newline="\n")
    (output_dir / "calibration_label_manifest.json").write_text(manifest_text, encoding="utf-8", newline="\n")
    (output_dir / "calibration_label_manifest.md").write_text(markdown_text, encoding="utf-8", newline="\n")
    (output_dir / "SHA256SUMS.txt").write_text(checksums_text, encoding="utf-8", newline="\n")


def _review_ready_run(db_path, cache_root, tmp_path, run_id: str) -> dict:
    run_summary = _bootstrap_scaffolded_run(db_path, cache_root, run_id)
    review_repository = ReviewRepository(db_path)
    required_review_count = max(
        2,
        int(len(run_summary["candidate_ids"]) * 0.20 + 0.999999),
        int(min(len(run_summary["candidate_ids"]), 20) * 0.50 + 0.999999),
    )
    approved_ids = run_summary["candidate_ids"][: max(1, required_review_count // 2)]
    watched_ids = run_summary["candidate_ids"][max(1, required_review_count // 2) : required_review_count]
    if not watched_ids:
        watched_ids = [run_summary["candidate_ids"][max(1, required_review_count // 2)]]
    for candidate_id in approved_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id=run_id,
            reviewer_id="reviewer-001",
            decision="approve_for_archive_quote",
            note="approved for calibration artifact",
        )
    for candidate_id in watched_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id=run_id,
            reviewer_id="reviewer-001",
            decision="watch",
            note="watchlisted for calibration artifact",
        )
    export_repository = ExportRepository(db_path, export_root=tmp_path)
    export_repository.persist_export(
        run_id=run_id,
        audience="report_pdf",
        requested_precision="restricted",
        candidates=export_repository.fetch_export_candidates(run_id),
    )
    return run_summary


def test_calibration_label_pack_ready_and_pending_toggle(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-pack.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    run_summary = _bootstrap_scaffolded_run(db_path, cache_root, "run-001")
    review_repository = ReviewRepository(db_path)
    required_review_count = max(
        2,
        int(len(run_summary["candidate_ids"]) * 0.20 + 0.999999),
        int(min(len(run_summary["candidate_ids"]), 20) * 0.50 + 0.999999),
    )
    approved_ids = run_summary["candidate_ids"][: max(1, required_review_count // 2)]
    watched_ids = run_summary["candidate_ids"][max(1, required_review_count // 2) : required_review_count]
    if not watched_ids:
        watched_ids = [run_summary["candidate_ids"][max(1, required_review_count // 2)]]

    for candidate_id in approved_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id="run-001",
            reviewer_id="reviewer-001",
            decision="approve_for_archive_quote",
            note="approved for calibration labels",
        )
    for candidate_id in watched_ids:
        review_repository.decide(
            candidate_id=candidate_id,
            run_id="run-001",
            reviewer_id="reviewer-001",
            decision="watch",
            note="watchlisted for calibration labels",
        )

    export_repository = ExportRepository(db_path, export_root=tmp_path)
    export_repository.persist_export(
        run_id="run-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=export_repository.fetch_export_candidates("run-001"),
    )

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-pack", "--run-id", "run-001"]) == 0
    pack = json.loads(output.getvalue())

    repeated_output = io.StringIO()
    with redirect_stdout(repeated_output):
        assert main(["calibration-label-pack", "--run-id", "run-001"]) == 0
    repeated_pack = json.loads(repeated_output.getvalue())

    pending_output = io.StringIO()
    with redirect_stdout(pending_output):
        assert main(["calibration-label-pack", "--run-id", "run-001", "--include-pending"]) == 0
    pending_pack = json.loads(pending_output.getvalue())

    assert pack["status"] == "ready"
    assert set(pack.keys()) >= {
        "run_id",
        "status",
        "reasons",
        "calibration_policy_id",
        "calibration_policy",
        "processing_baseline_id",
        "score_formula_version",
        "source_scene_manifest_hash",
        "legal_gate",
        "composite_quality",
        "candidate_count",
        "review_state_counts",
        "reviewed_candidate_count",
        "approved_candidate_count",
        "rejected_candidate_count",
        "watched_candidate_count",
        "pending_candidate_count",
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "label_pack_hash",
        "labels",
    }
    assert pack["reviewed_candidate_count"] == len(approved_ids) + len(watched_ids)
    assert pack["approved_candidate_count"] == len(approved_ids)
    assert pack["watched_candidate_count"] == len(watched_ids)
    assert pack["review_state_counts"] == {
        "approved_for_archive_quote": len(approved_ids),
        "pending_review": len(run_summary["candidate_ids"]) - (len(approved_ids) + len(watched_ids)),
        "watch": len(watched_ids),
    }
    assert pack["pending_candidate_count"] == len(run_summary["candidate_ids"]) - (
        len(approved_ids) + len(watched_ids)
    )
    assert pack["export_audit_ready"] is True
    assert pack["label_pack_hash"] == repeated_pack["label_pack_hash"]
    assert all(label["review_state"] != "pending_review" for label in pack["labels"])
    assert any(label["review_state"] == "pending_review" for label in pending_pack["labels"])
    assert pending_pack["review_state_counts"] == pack["review_state_counts"]


def test_calibration_label_pack_no_review_and_markdown(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-pack-markdown.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _bootstrap_scaffolded_run(db_path, cache_root, "run-001")

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-pack", "--run-id", "run-001"]) == 0
    pack = json.loads(output.getvalue())

    markdown_output = io.StringIO()
    with redirect_stdout(markdown_output):
        assert main(["calibration-label-pack", "--run-id", "run-001", "--output", "markdown"]) == 0
    markdown = markdown_output.getvalue()

    assert pack["status"] == "incomplete"
    assert "No reviewed candidates available for calibration label pack" in pack["reasons"]
    assert "# Calibration Label Pack" in markdown
    assert "Status: `incomplete`" in markdown
    assert "## Reasons" in markdown


def test_calibration_label_pack_fails_for_legal_denied_run(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-pack-denied.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _bootstrap_scaffolded_run(
        db_path,
        cache_root,
        "run-denied",
        legal_gate=_legal_gate_fail(),
    )

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-pack", "--run-id", "run-denied"]) == 1
    pack = json.loads(output.getvalue())

    assert pack["status"] == "fail"
    assert pack["legal_gate"]["decision"] == "fail"
    assert "Legal gate failed: attestation missing" in pack["reasons"]


def test_calibration_label_manifest_ready_hash_and_markdown(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-manifest.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)

    run_summary = _bootstrap_scaffolded_run(db_path, cache_root, "run-001")
    review_repository = ReviewRepository(db_path)
    approved_id = run_summary["candidate_ids"][0]
    watched_id = run_summary["candidate_ids"][1]
    review_repository.decide(
        candidate_id=approved_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="approve_for_archive_quote",
        note="approved for manifest",
    )
    review_repository.decide(
        candidate_id=watched_id,
        run_id="run-001",
        reviewer_id="reviewer-001",
        decision="watch",
        note="watch for manifest",
    )

    export_repository = ExportRepository(db_path, export_root=tmp_path)
    export_repository.persist_export(
        run_id="run-001",
        audience="report_pdf",
        requested_precision="restricted",
        candidates=export_repository.fetch_export_candidates("run-001"),
    )

    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-manifest", "--run-id", "run-001"]) == 0
    manifest = json.loads(output.getvalue())

    repeated_output = io.StringIO()
    with redirect_stdout(repeated_output):
        assert main(["calibration-label-manifest", "--run-id", "run-001"]) == 0
    repeated_manifest = json.loads(repeated_output.getvalue())

    pending_output = io.StringIO()
    with redirect_stdout(pending_output):
        assert main(["calibration-label-manifest", "--run-id", "run-001", "--include-pending"]) == 0
    pending_manifest = json.loads(pending_output.getvalue())

    markdown_output = io.StringIO()
    with redirect_stdout(markdown_output):
        assert main(["calibration-label-manifest", "--run-id", "run-001", "--output", "markdown"]) == 0
    markdown = markdown_output.getvalue()

    assert manifest["status"] == "ready"
    assert set(manifest.keys()) >= {
        "run_id",
        "status",
        "reasons",
        "manifest_type",
        "manifest_version",
        "calibration_policy_id",
        "calibration_policy",
        "processing_baseline_id",
        "score_formula_version",
        "source_scene_manifest_hash",
        "legal_gate",
        "composite_quality",
        "candidate_count",
        "review_state_counts",
        "reviewed_candidate_count",
        "approved_candidate_count",
        "rejected_candidate_count",
        "watched_candidate_count",
        "pending_candidate_count",
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "include_pending",
        "label_count",
        "label_pack_hash",
        "label_manifest_hash",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "label_ids",
    }
    assert manifest["manifest_type"] == "calibration_label_pack_manifest"
    assert manifest["manifest_version"] == 1
    assert manifest["include_pending"] is False
    assert manifest["label_manifest_hash"] == repeated_manifest["label_manifest_hash"]
    assert pending_manifest["include_pending"] is True
    assert pending_manifest["label_count"] >= manifest["label_count"]
    assert pending_manifest["label_manifest_hash"] != manifest["label_manifest_hash"]
    assert "# Calibration Label Manifest" in markdown
    assert "Status: `ready`" in markdown
    assert "## Reasons" in markdown


def test_calibration_label_manifest_incomplete_and_fail(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-manifest-status.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _bootstrap_scaffolded_run(db_path, cache_root, "run-001")
    _bootstrap_scaffolded_run(
        db_path,
        cache_root,
        "run-denied",
        legal_gate=_legal_gate_fail(),
    )

    incomplete_output = io.StringIO()
    with redirect_stdout(incomplete_output):
        assert main(["calibration-label-manifest", "--run-id", "run-001"]) == 0
    incomplete_manifest = json.loads(incomplete_output.getvalue())

    fail_output = io.StringIO()
    with redirect_stdout(fail_output):
        assert main(["calibration-label-manifest", "--run-id", "run-denied"]) == 1
    fail_manifest = json.loads(fail_output.getvalue())

    assert incomplete_manifest["status"] == "incomplete"
    assert "No reviewed candidates available for calibration label pack" in incomplete_manifest["reasons"]
    assert fail_manifest["status"] == "fail"
    assert fail_manifest["legal_gate"]["decision"] == "fail"
    assert "Legal gate failed: attestation missing" in fail_manifest["reasons"]


def test_calibration_label_export_writes_deterministic_artifacts(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-export.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _review_ready_run(db_path, cache_root, tmp_path, "run-001")

    output_dir = tmp_path / "artifact-a"
    output = io.StringIO()
    with redirect_stdout(output):
        assert main(["calibration-label-export", "--run-id", "run-001", "--output-dir", str(output_dir)]) == 0
    export = json.loads(output.getvalue())

    repeated_output = io.StringIO()
    with redirect_stdout(repeated_output):
        assert main(["calibration-label-export", "--run-id", "run-001", "--output-dir", str(output_dir)]) == 0
    repeated_export = json.loads(repeated_output.getvalue())

    other_output_dir = tmp_path / "artifact-b"
    other_output = io.StringIO()
    with redirect_stdout(other_output):
        assert main(["calibration-label-export", "--run-id", "run-001", "--output-dir", str(other_output_dir)]) == 0
    other_export = json.loads(other_output.getvalue())

    pending_output = io.StringIO()
    with redirect_stdout(pending_output):
        assert main(
            [
                "calibration-label-export",
                "--run-id",
                "run-001",
                "--output-dir",
                str(tmp_path / "artifact-pending"),
                "--include-pending",
            ]
        ) == 0
    pending_export = json.loads(pending_output.getvalue())

    assert export["status"] == "ready"
    assert set(export.keys()) >= {
        "run_id",
        "status",
        "reasons",
        "output_dir",
        "include_pending",
        "label_pack_hash",
        "label_manifest_hash",
        "artifact_hash",
        "files",
        "file_hashes",
    }
    assert export["files"] == [
        "calibration_label_pack.json",
        "calibration_label_manifest.json",
        "calibration_label_manifest.md",
        "SHA256SUMS.txt",
    ]
    assert export["include_pending"] is False
    assert export["artifact_hash"] == repeated_export["artifact_hash"]
    assert export["artifact_hash"] == other_export["artifact_hash"]
    assert pending_export["include_pending"] is True
    assert pending_export["artifact_hash"] != export["artifact_hash"]
    assert export["artifact_hash"] == _expected_artifact_hash(export, output_dir)
    assert repeated_export["artifact_hash"] == _expected_artifact_hash(repeated_export, output_dir)
    assert other_export["artifact_hash"] == _expected_artifact_hash(other_export, other_output_dir)

    without_markdown_hash = _stable_hash(
        {
            "run_id": export["run_id"],
            "include_pending": export["include_pending"],
            "files": [
                {"name": file_name, "sha256": export["file_hashes"][file_name]}
                for file_name in export["files"]
                if file_name != "calibration_label_manifest.md"
            ],
        }
    )
    assert without_markdown_hash != export["artifact_hash"]

    without_sha_file_hash = _stable_hash(
        {
            "run_id": export["run_id"],
            "include_pending": export["include_pending"],
            "files": [
                {"name": file_name, "sha256": export["file_hashes"][file_name]}
                for file_name in export["files"]
                if file_name != "SHA256SUMS.txt"
            ],
        }
    )
    assert without_sha_file_hash != export["artifact_hash"]

    for file_name in export["files"]:
        path = output_dir / file_name
        assert path.exists()
        assert export["file_hashes"][file_name] == _file_hash(path)

    checksums = (output_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
    repeated_checksums = (other_output_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert checksums == repeated_checksums
    assert "SHA256SUMS.txt  SHA256SUMS.txt" not in checksums
    assert f"{export['file_hashes']['SHA256SUMS.txt']}  SHA256SUMS.txt" not in checksums
    for file_name in export["files"]:
        if file_name == "SHA256SUMS.txt":
            continue
        assert f"{export['file_hashes'][file_name]}  {file_name}" in checksums

    pack = json.loads((output_dir / "calibration_label_pack.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "calibration_label_manifest.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "calibration_label_manifest.md").read_text(encoding="utf-8")
    assert pack["label_pack_hash"] == export["label_pack_hash"]
    assert manifest["label_manifest_hash"] == export["label_manifest_hash"]
    assert "Artifact hash:" in markdown
    assert export["artifact_hash"] in markdown

    tampered_markdown = markdown.replace("# Calibration Label Artifact Export", "# Calibration Label Artifact Export (tampered)")
    canonical_tampered_hashes = {
        "calibration_label_pack.json": _file_hash(output_dir / "calibration_label_pack.json"),
        "calibration_label_manifest.json": _file_hash(output_dir / "calibration_label_manifest.json"),
        "calibration_label_manifest.md": sha256(
            _canonical_markdown_for_artifact_hash(tampered_markdown).encode("utf-8")
        ).hexdigest(),
    }
    canonical_tampered_hashes["SHA256SUMS.txt"] = sha256(
        _render_checksums(canonical_tampered_hashes).encode("utf-8")
    ).hexdigest()
    tampered_artifact_hash = _stable_hash(
        {
            "run_id": export["run_id"],
            "include_pending": export["include_pending"],
            "files": [
                {"name": file_name, "sha256": canonical_tampered_hashes[file_name]}
                for file_name in export["files"]
            ],
        }
    )
    assert tampered_artifact_hash != export["artifact_hash"]


def test_calibration_label_export_incomplete_and_fail_statuses(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-export-status.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _bootstrap_scaffolded_run(db_path, cache_root, "run-001")
    _bootstrap_scaffolded_run(
        db_path,
        cache_root,
        "run-denied",
        legal_gate=_legal_gate_fail(),
    )

    incomplete_output_dir = tmp_path / "artifact-incomplete"
    incomplete_output = io.StringIO()
    with redirect_stdout(incomplete_output):
        assert main(
            [
                "calibration-label-export",
                "--run-id",
                "run-001",
                "--output-dir",
                str(incomplete_output_dir),
            ]
        ) == 0
    incomplete_export = json.loads(incomplete_output.getvalue())

    fail_output_dir = tmp_path / "artifact-fail"
    fail_output = io.StringIO()
    with redirect_stdout(fail_output):
        assert main(
            [
                "calibration-label-export",
                "--run-id",
                "run-denied",
                "--output-dir",
                str(fail_output_dir),
            ]
        ) == 1
    fail_export = json.loads(fail_output.getvalue())

    assert incomplete_export["status"] == "incomplete"
    assert "No reviewed candidates available for calibration label pack" in incomplete_export["reasons"]
    assert (incomplete_output_dir / "calibration_label_pack.json").exists()
    assert (incomplete_output_dir / "calibration_label_manifest.json").exists()
    assert fail_export["status"] == "fail"
    assert "Legal gate failed: attestation missing" in fail_export["reasons"]
    assert (fail_output_dir / "calibration_label_pack.json").exists()
    assert (fail_output_dir / "calibration_label_manifest.json").exists()


def test_calibration_label_verify_validates_ready_incomplete_and_fail_artifacts(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-verify.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _review_ready_run(db_path, cache_root, tmp_path, "run-ready")
    _bootstrap_scaffolded_run(db_path, cache_root, "run-incomplete")
    _bootstrap_scaffolded_run(db_path, cache_root, "run-fail", legal_gate=_legal_gate_fail())

    ready_dir = tmp_path / "ready-artifact"
    incomplete_dir = tmp_path / "incomplete-artifact"
    fail_dir = tmp_path / "fail-artifact"
    assert _export_artifact("run-ready", ready_dir)[0] == 0
    assert _export_artifact("run-incomplete", incomplete_dir)[0] == 0
    assert _export_artifact("run-fail", fail_dir)[0] == 1

    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)

    ready_exit, ready_verify = _verify_artifact(ready_dir)
    incomplete_exit, incomplete_verify = _verify_artifact(incomplete_dir)
    fail_exit, fail_verify = _verify_artifact(fail_dir)

    assert ready_exit == 0
    assert incomplete_exit == 0
    assert fail_exit == 0
    for verify in (ready_verify, incomplete_verify, fail_verify):
        assert verify["status"] == "valid"
        assert verify["sha256sums_valid"] is True
        assert verify["artifact_hash_valid"] is True
        assert verify["label_pack_hash_valid"] is True
        assert verify["label_manifest_hash_valid"] is True
        assert verify["manifest_cross_checks_valid"] is True
        assert verify["reasons"] == ["Calibration label artifact is valid"]


def test_calibration_label_verify_detects_tampering_and_missing_files(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-verify-tamper.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _review_ready_run(db_path, cache_root, tmp_path, "run-001")

    base_dir = tmp_path / "base-artifact"
    assert _export_artifact("run-001", base_dir)[0] == 0
    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)

    pack_tamper_dir = tmp_path / "pack-tamper"
    manifest_tamper_dir = tmp_path / "manifest-tamper"
    markdown_tamper_dir = tmp_path / "markdown-tamper"
    sums_tamper_dir = tmp_path / "sums-tamper"
    missing_file_dir = tmp_path / "missing-file"
    for target in (pack_tamper_dir, manifest_tamper_dir, markdown_tamper_dir, sums_tamper_dir, missing_file_dir):
        target.mkdir()
        for file_name in ("calibration_label_pack.json", "calibration_label_manifest.json", "calibration_label_manifest.md", "SHA256SUMS.txt"):
            (target / file_name).write_bytes((base_dir / file_name).read_bytes())

    (pack_tamper_dir / "calibration_label_pack.json").write_text(
        (pack_tamper_dir / "calibration_label_pack.json").read_text(encoding="utf-8").replace('"status": "ready"', '"status": "tampered"', 1),
        encoding="utf-8",
        newline="\n",
    )
    (manifest_tamper_dir / "calibration_label_manifest.json").write_text(
        (manifest_tamper_dir / "calibration_label_manifest.json").read_text(encoding="utf-8").replace('"status": "ready"', '"status": "tampered"', 1),
        encoding="utf-8",
        newline="\n",
    )
    (markdown_tamper_dir / "calibration_label_manifest.md").write_text(
        (markdown_tamper_dir / "calibration_label_manifest.md").read_text(encoding="utf-8").replace("Status: `ready`", "Status: `tampered`", 1),
        encoding="utf-8",
        newline="\n",
    )
    (sums_tamper_dir / "SHA256SUMS.txt").write_text(
        (sums_tamper_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").replace("a", "b", 1),
        encoding="utf-8",
        newline="\n",
    )
    (missing_file_dir / "calibration_label_manifest.md").unlink()

    for artifact_dir in (
        pack_tamper_dir,
        manifest_tamper_dir,
        markdown_tamper_dir,
        sums_tamper_dir,
        missing_file_dir,
    ):
        exit_code, verify = _verify_artifact(artifact_dir)
        assert exit_code == 1
        assert verify["status"] == "invalid"


def test_calibration_label_verify_rejects_coordinate_fields_and_renders_markdown(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-verify-coordinate.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _review_ready_run(db_path, cache_root, tmp_path, "run-001")

    output_dir = tmp_path / "artifact"
    _, export = _export_artifact("run-001", output_dir)
    pack = json.loads((output_dir / "calibration_label_pack.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "calibration_label_manifest.json").read_text(encoding="utf-8"))
    pack["labels"][0]["lon"] = -79.0
    pack["label_pack_hash"] = _stable_hash(
        {
            "run_id": pack["run_id"],
            "calibration_policy_id": pack["calibration_policy_id"],
            "latest_export_audit_manifest_hash": pack["latest_export_audit_manifest_hash"],
            "labels": pack["labels"],
        }
    )
    manifest["label_pack_hash"] = pack["label_pack_hash"]
    manifest["label_manifest_hash"] = _stable_hash(
        {
            "manifest_type": manifest["manifest_type"],
            "manifest_version": manifest["manifest_version"],
            "run_id": manifest["run_id"],
            "calibration_policy_id": manifest["calibration_policy_id"],
            "processing_baseline_id": manifest["processing_baseline_id"],
            "score_formula_version": manifest["score_formula_version"],
            "source_scene_manifest_hash": manifest["source_scene_manifest_hash"],
            "latest_export_audit_manifest_hash": manifest["latest_export_audit_manifest_hash"],
            "include_pending": manifest["include_pending"],
            "label_pack_hash": manifest["label_pack_hash"],
            "label_ids": manifest["label_ids"],
        }
    )
    canonical_markdown_hashes = {
        "calibration_label_pack.json": sha256((json.dumps(pack, indent=2, sort_keys=True) + "\n").encode("utf-8")).hexdigest(),
        "calibration_label_manifest.json": sha256((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")).hexdigest(),
        "calibration_label_manifest.md": sha256(
            "\n".join(
                [
                    "# Calibration Label Artifact Export",
                    "",
                    f"- Run ID: `{manifest['run_id']}`",
                    f"- Status: `{manifest['status']}`",
                    f"- Include pending: `{manifest['include_pending']}`",
                    f"- Label count: `{manifest['label_count']}`",
                    f"- Label pack hash: `{manifest['label_pack_hash']}`",
                    f"- Label manifest hash: `{manifest['label_manifest_hash']}`",
                    "- Artifact hash: `<artifact_hash_excluded_from_hash_input>`",
                    "",
                    "## Files",
                    "",
                    "- `calibration_label_pack.json`",
                    "- `calibration_label_manifest.json`",
                    "- `calibration_label_manifest.md`",
                    "- `SHA256SUMS.txt`",
                    "",
                    "## Reasons",
                    "",
                    *[f"- {reason}" for reason in manifest["reasons"]],
                    "",
                ]
            ).encode("utf-8")
        ).hexdigest(),
    }
    canonical_markdown_hashes["SHA256SUMS.txt"] = sha256(
        _render_checksums(canonical_markdown_hashes).encode("utf-8")
    ).hexdigest()
    artifact_hash = _stable_hash(
        {
            "run_id": export["run_id"],
            "include_pending": export["include_pending"],
            "files": [
                {"name": file_name, "sha256": canonical_markdown_hashes[file_name]}
                for file_name in export["files"]
            ],
        }
    )
    _rewrite_artifact_files(output_dir, pack, manifest, artifact_hash)

    exit_code, verify = _verify_artifact(output_dir)
    assert exit_code == 1
    assert verify["status"] == "invalid"
    assert "Label includes forbidden coordinate field: lon" in verify["reasons"]

    markdown_exit, markdown = _verify_artifact(output_dir, output="markdown")
    assert markdown_exit == 1
    assert "# Calibration Label Artifact Verification" in markdown
    assert "Status: `invalid`" in markdown
    assert "## Reasons" in markdown


def test_calibration_label_verify_missing_artifact_hash_line_is_invalid(monkeypatch, tmp_path):
    db_path = tmp_path / "calibration-label-verify-missing-hash.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(db_path))
    init_db(db_path)
    _review_ready_run(db_path, cache_root, tmp_path, "run-001")

    output_dir = tmp_path / "artifact"
    assert _export_artifact("run-001", output_dir)[0] == 0
    monkeypatch.delenv("LAWFUL_ANOMALY_DB_PATH", raising=False)
    (output_dir / "calibration_label_manifest.md").write_text(
        (output_dir / "calibration_label_manifest.md").read_text(encoding="utf-8").replace(
            "- Artifact hash: `", "- Artifact hash removed: `", 1
        ),
        encoding="utf-8",
        newline="\n",
    )

    exit_code, verify = _verify_artifact(output_dir)
    assert exit_code == 1
    assert verify["status"] == "invalid"
    assert "Artifact hash line missing from calibration_label_manifest.md" in verify["reasons"]


def test_calibration_label_register_and_registry_list_are_deterministic(monkeypatch, tmp_path):
    generation_db = tmp_path / "calibration-label-registry-generation.sqlite3"
    registry_db = tmp_path / "calibration-label-registry.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(generation_db))
    init_db(generation_db)
    _review_ready_run(generation_db, cache_root, tmp_path, "run-ready")
    _bootstrap_scaffolded_run(generation_db, cache_root, "run-incomplete")
    _bootstrap_scaffolded_run(generation_db, cache_root, "run-fail", legal_gate=_legal_gate_fail())

    ready_dir = tmp_path / "ready-artifact"
    incomplete_dir = tmp_path / "incomplete-artifact"
    fail_dir = tmp_path / "fail-artifact"
    assert _export_artifact("run-ready", ready_dir)[0] == 0
    assert _export_artifact("run-incomplete", incomplete_dir)[0] == 0
    assert _export_artifact("run-fail", fail_dir)[0] == 1

    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(registry_db))
    init_db(registry_db)

    ready_output = io.StringIO()
    with redirect_stdout(ready_output):
        assert main(["calibration-label-register", "--artifact-dir", str(ready_dir)]) == 0
    ready_register = json.loads(ready_output.getvalue())

    duplicate_output = io.StringIO()
    with redirect_stdout(duplicate_output):
        assert main(["calibration-label-register", "--artifact-dir", str(ready_dir)]) == 0
    duplicate_register = json.loads(duplicate_output.getvalue())

    incomplete_output = io.StringIO()
    with redirect_stdout(incomplete_output):
        assert main(["calibration-label-register", "--artifact-dir", str(incomplete_dir)]) == 0
    incomplete_register = json.loads(incomplete_output.getvalue())

    fail_output = io.StringIO()
    with redirect_stdout(fail_output):
        assert main(["calibration-label-register", "--artifact-dir", str(fail_dir)]) == 0
    fail_register = json.loads(fail_output.getvalue())

    list_output = io.StringIO()
    with redirect_stdout(list_output):
        assert main(["calibration-label-registry-list"]) == 0
    registry_list = json.loads(list_output.getvalue())

    markdown_output = io.StringIO()
    with redirect_stdout(markdown_output):
        assert main(["calibration-label-registry-list", "--output", "markdown"]) == 0
    registry_markdown = markdown_output.getvalue()

    assert ready_register["status"] == "registered"
    assert duplicate_register["status"] == "already_registered"
    assert duplicate_register["artifact_hash"] == ready_register["artifact_hash"]
    assert "artifact_dir" not in ready_register["registry_record"]["verification"]
    assert incomplete_register["status"] == "registered"
    assert incomplete_register["artifact_status"] == "incomplete"
    assert fail_register["status"] == "registered"
    assert fail_register["artifact_status"] == "fail"
    assert registry_list["status"] == "ok"
    assert registry_list["artifact_count"] == 3
    assert [artifact["run_id"] for artifact in registry_list["artifacts"]] == [
        "run-fail",
        "run-incomplete",
        "run-ready",
    ]
    assert "# Calibration Label Artifact Registry" in registry_markdown
    assert "Artifact count:" in registry_markdown


def test_calibration_label_register_rejects_invalid_artifact_without_persisting(monkeypatch, tmp_path):
    generation_db = tmp_path / "calibration-label-registry-invalid-generation.sqlite3"
    registry_db = tmp_path / "calibration-label-registry-invalid.sqlite3"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(generation_db))
    init_db(generation_db)
    _review_ready_run(generation_db, cache_root, tmp_path, "run-001")

    artifact_dir = tmp_path / "artifact"
    assert _export_artifact("run-001", artifact_dir)[0] == 0
    (artifact_dir / "SHA256SUMS.txt").write_text(
        (artifact_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").replace("a", "b", 1),
        encoding="utf-8",
        newline="\n",
    )

    monkeypatch.setenv("LAWFUL_ANOMALY_DB_PATH", str(registry_db))
    init_db(registry_db)

    register_output = io.StringIO()
    with redirect_stdout(register_output):
        assert main(["calibration-label-register", "--artifact-dir", str(artifact_dir)]) == 1
    register_result = json.loads(register_output.getvalue())

    list_output = io.StringIO()
    with redirect_stdout(list_output):
        assert main(["calibration-label-registry-list"]) == 0
    registry_list = json.loads(list_output.getvalue())

    markdown_output = io.StringIO()
    with redirect_stdout(markdown_output):
        assert main(["calibration-label-register", "--artifact-dir", str(artifact_dir), "--output", "markdown"]) == 1
    register_markdown = markdown_output.getvalue()

    assert register_result["status"] == "invalid"
    assert register_result["registry_record"] is None
    assert registry_list["artifact_count"] == 0
    assert "# Calibration Label Artifact Registration" in register_markdown
    assert "Status: `invalid`" in register_markdown
