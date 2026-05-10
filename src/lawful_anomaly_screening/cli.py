from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from datetime import datetime

from . import __version__
from .aoi.validation import validate_aoi_file
from .db.repositories.acceptance_repository import AcceptanceRepository
from .db.repositories.calibration_artifact_repository import CalibrationArtifactRepository
from .db.repositories.export_repository import ExportRepository
from .db.repositories.manifest_repository import ManifestRepository
from .db.repositories.paid_repository import PaidRepository
from .db.repositories.review_repository import ReviewRepository
from .db.repositories.run_repository import RunRepository
from .db.sqlite import bootstrap_minimal_run, init_db
from .db.sqlite import bootstrap_gate_failed_run
from .exceptions import (
    ExportPolicyError,
    LegalGateError,
    PaidFlowError,
    ReviewDecisionError,
    ReviewStateError,
    SourceError,
)
from .exports.bundle_verifier import (
    render_bundle_verify_markdown,
    render_bundle_verify_batch_markdown,
    verify_export_bundle,
    verify_export_bundle_batch,
)
from .releases.evidence_index_verifier import (
    load_evidence_list,
    render_release_evidence_index_markdown,
    verify_release_evidence_index,
)
from .releases.evidence_verifier import (
    render_release_evidence_verify_markdown,
    verify_release_evidence,
)
from .exports.precision_policy import normalize_export_tier
from .orchestration.scaffold_run import scaffold_run_for_run_id
from .orchestration.run_pipeline import execute_run
from .legal import (
    LEGAL_GATE_DECISION_PASS,
    LEGAL_OUTCOME_ALLOWED,
    build_legal_gate_record,
    evaluate_legal_gate,
)
from .legal.geofence import load_geofence_policy
from .paid.order_service import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_CONFIRMED,
    ORDER_STATUS_DELIVERED,
    OrderService,
)
from .paid.quote_service import QuoteService
from .paid.up42_archive import Up42ArchiveClient
from .settings import load_settings
from .sources.earth_search import load_endpoint_registry
from .sources.manifest_builder import build_manifest
from .orchestration.acceptance import (
    build_acceptance_summary,
    build_calibration_label_manifest,
    build_calibration_label_pack,
    build_calibration_pack,
    build_kpi_summary,
    render_calibration_label_manifest_markdown,
    render_calibration_label_pack_markdown,
    render_calibration_pack_markdown,
    render_acceptance_summary_markdown,
    reproducibility_check,
    top10_stability_rate,
)


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_baseline() -> dict:
    return _load_json(load_settings().baseline_path)


def _stable_json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _stable_hash(payload: dict) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_legal_gate_for_aoi(
    args: argparse.Namespace,
    *,
    aoi_path: str,
    aoi_hash: str,
) -> dict[str, str]:
    settings = load_settings()
    return build_legal_gate_record(
        attestation_status=getattr(args, "attestation", None),
        geofence_status=getattr(args, "geofence", None),
        aoi_path=aoi_path,
        aoi_hash=aoi_hash,
        geofence_policy=load_geofence_policy(settings.geofence_policy_path),
    ).as_dict()


def _validate_date_window(start_str: str | None, end_str: str | None) -> tuple[str, str]:
    if not start_str or not end_str:
        raise ValueError("--start-date and --end-date are required")

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError("dates must be in YYYY-MM-DD format")

    if end_date < start_date:
        raise ValueError("end-date cannot be before start-date")

    return start_str, end_str


def _legal_gate_outcome(args: argparse.Namespace) -> str:
    return evaluate_legal_gate(
        attestation_status=getattr(args, "attestation", None),
        geofence_status=getattr(args, "geofence", None),
    )


def cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_show_config(_: argparse.Namespace) -> int:
    settings = load_settings()
    print(
        json.dumps(
            {
                "db_path": str(settings.db_path),
                "baseline_path": str(settings.baseline_path),
                "logging_config_path": str(settings.logging_config_path),
                "export_precision_path": str(settings.export_precision_path),
                "endpoints_path": str(settings.endpoints_path),
                "geofence_policy_path": str(settings.geofence_policy_path),
                "preprocessing_config_path": str(settings.preprocessing_config_path),
            },
            indent=2,
        )
    )
    return 0


def cmd_show_baseline(_: argparse.Namespace) -> int:
    print(json.dumps(_load_baseline(), indent=2))
    return 0


def cmd_init_db(_: argparse.Namespace) -> int:
    init_db(load_settings().db_path)
    print("ok")
    return 0


def cmd_validate_aoi(_: argparse.Namespace) -> int:
    print("AOI validation scaffold ready")
    return 0


def cmd_legal_check(_: argparse.Namespace) -> int:
    outcome = _legal_gate_outcome(_)
    print(outcome)
    if outcome == LEGAL_OUTCOME_ALLOWED:
        return 0
    return 1


def cmd_create_run(_: argparse.Namespace) -> int:
    settings = load_settings()
    baseline = _load_baseline()
    init_db(settings.db_path)

    if not _.aoi_path:
        raise ValueError("--aoi-path is required")
    aoi_metadata = validate_aoi_file(_.aoi_path)

    start_date, end_date = _validate_date_window(_.start_date, _.end_date)
    run_id = _.run_id or f"run-{aoi_metadata['aoi_hash'][:8]}"
    legal_gate = _build_legal_gate_for_aoi(
        _,
        aoi_path=aoi_metadata["aoi_path"],
        aoi_hash=aoi_metadata["aoi_hash"],
    )
    if legal_gate["decision"] != LEGAL_GATE_DECISION_PASS:
        bootstrap_gate_failed_run(
            settings.db_path,
            processing_baseline_id=baseline["processing_baseline_id"],
            score_formula_version=baseline["score_formula_version"],
            run_id=run_id,
            aoi_path=aoi_metadata.get("aoi_path"),
            aoi_geometry_type=aoi_metadata.get("aoi_geometry_type"),
            aoi_geometry=aoi_metadata.get("aoi_geometry"),
            aoi_bbox=aoi_metadata.get("aoi_bbox"),
            aoi_hash=aoi_metadata.get("aoi_hash"),
            start_date=start_date,
            end_date=end_date,
            legal_gate=legal_gate,
        )
        raise LegalGateError(legal_gate["reason"])

    registry = load_endpoint_registry()
    manifest = build_manifest(
        source_endpoint_id=_.source_endpoint_id,
        aoi_hash=aoi_metadata.get("aoi_hash"),
        aoi_bbox=aoi_metadata.get("aoi_bbox"),
        start_date=start_date,
        end_date=end_date,
    )
    manifest_repository = ManifestRepository(settings.db_path)
    manifest_record = manifest_repository.persist_manifest(manifest)

    run_record = bootstrap_minimal_run(
        settings.db_path,
        processing_baseline_id=baseline["processing_baseline_id"],
        score_formula_version=baseline["score_formula_version"],
        source_scene_manifest_hash=manifest_record["source_scene_manifest_hash"],
        source_endpoint_id=manifest_record["source_endpoint_id"],
        run_id=run_id,
        source_name=manifest_record["source_name"],
        manifest_path=manifest_record["manifest_path"],
        aoi_path=aoi_metadata.get("aoi_path"),
        aoi_geometry_type=aoi_metadata.get("aoi_geometry_type"),
        aoi_geometry=aoi_metadata.get("aoi_geometry"),
        aoi_bbox=aoi_metadata.get("aoi_bbox"),
        aoi_hash=aoi_metadata.get("aoi_hash"),
        start_date=start_date,
        end_date=end_date,
        legal_gate=legal_gate,
    )
    if "fallback_diagnostics" in manifest:
        run_record["fallback_diagnostics"] = manifest["fallback_diagnostics"]
    print(json.dumps(run_record, indent=2))
    return 0


def cmd_scaffold_run(args: argparse.Namespace) -> int:
    try:
        summary = scaffold_run_for_run_id(
            load_settings().db_path,
            run_id=args.run_id,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


def cmd_execute_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    run_repository = RunRepository(settings.db_path)
    run_metadata = run_repository.fetch_run(args.run_id)

    if run_metadata is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1

    if run_metadata["legal_gate"]["decision"] != LEGAL_GATE_DECISION_PASS:
        print(
            f"run {args.run_id} blocked by legal gate: {run_metadata['legal_gate']['reason']}",
            file=sys.stderr,
        )
        return 1

    if not run_metadata.get("aoi_hash") or not run_metadata.get("start_date"):
        print(f"run {args.run_id} is missing AOI or date window metadata", file=sys.stderr)
        return 1

    try:
        summary = execute_run(
            settings.db_path,
            run_id=args.run_id,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


def cmd_review_queue(args: argparse.Namespace) -> int:
    repository = ReviewRepository(load_settings().db_path)
    queue = repository.list_review_queue(run_id=args.run_id, limit=args.limit)
    print(json.dumps(queue, indent=2))
    return 0


def cmd_review_show(args: argparse.Namespace) -> int:
    repository = ReviewRepository(load_settings().db_path)
    candidate = repository.fetch_candidate(args.candidate_id)
    if candidate is None:
        print(f"candidate not found: {args.candidate_id}", file=sys.stderr)
        return 1
    payload = {
        "candidate": candidate,
        "review_actions": repository.fetch_review_actions(args.candidate_id),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_review_decide(args: argparse.Namespace) -> int:
    repository = ReviewRepository(load_settings().db_path)
    action = repository.decide(
        candidate_id=args.candidate_id,
        run_id=args.run_id,
        reviewer_id=args.reviewer_id,
        decision=args.decision,
        note=args.note,
    )
    payload = {
        "review_action": action,
        "candidate": repository.fetch_candidate(args.candidate_id),
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_export_bundle_verify(args: argparse.Namespace) -> int:
    result = verify_export_bundle(
        bundle_manifest_path=args.bundle_manifest_path,
        export_root=Path(args.export_root) if args.export_root else None,
    )
    if args.output == "markdown":
        print(render_bundle_verify_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def cmd_export_bundle_verify_batch(args: argparse.Namespace) -> int:
    reports_dir = None
    manifest_list = None
    manifest_list_path = None
    if getattr(args, "reports_dir", None) and getattr(args, "manifest_list", None):
        print("Cannot use both --reports-dir and --manifest-list", file=sys.stderr)
        return 1
    if getattr(args, "reports_dir", None):
        reports_dir = Path(args.reports_dir)
    elif getattr(args, "manifest_list", None):
        from .exports.bundle_verifier import load_manifest_list
        manifest_list_path = args.manifest_list
        manifest_list = load_manifest_list(Path(manifest_list_path))
    else:
        reports_dir = Path("exports/reports")
    result = verify_export_bundle_batch(
        reports_dir=reports_dir,
        manifest_list=manifest_list,
        manifest_list_path=manifest_list_path,
        export_root=Path(args.export_root) if getattr(args, "export_root", None) else None,
        fail_fast=bool(getattr(args, "fail_fast", False)),
    )
    if args.output == "markdown":
        print(render_bundle_verify_batch_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def cmd_release_evidence_verify(args: argparse.Namespace) -> int:
    result = verify_release_evidence(args.evidence_dir)
    if args.output == "markdown":
        print(render_release_evidence_verify_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def cmd_release_evidence_index_verify(args: argparse.Namespace) -> int:
    evidence_root = getattr(args, "evidence_root", None)
    evidence_list_path = getattr(args, "evidence_list", None)
    if evidence_root and evidence_list_path:
        print("Cannot use both --evidence-root and --evidence-list", file=sys.stderr)
        return 1
    root_path = None
    evidence_list = None
    if evidence_list_path:
        evidence_list = load_evidence_list(Path(evidence_list_path))
    else:
        root_path = Path(evidence_root) if evidence_root else Path.cwd()
    result = verify_release_evidence_index(
        evidence_root=root_path,
        evidence_list=evidence_list,
        evidence_list_path=evidence_list_path,
        fail_fast=bool(getattr(args, "fail_fast", False)),
    )
    if args.output == "markdown":
        print(render_release_evidence_index_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def cmd_export_create(args: argparse.Namespace) -> int:
    repository = ExportRepository(load_settings().db_path)
    candidates = repository.fetch_export_candidates(args.run_id)
    if not candidates:
        run_repository = RunRepository(load_settings().db_path)
        run = run_repository.fetch_run(args.run_id)
        normalized_audience = normalize_export_tier(args.audience)
        if (
            run is not None
            and run.get("status") in {"completed", "review_ready"}
            and normalized_audience == "report_pdf"
            and args.requested_precision == "restricted"
        ):
            export_record = repository.persist_export(
                run_id=args.run_id,
                audience=args.audience,
                requested_precision=args.requested_precision,
                candidates=[],
            )
            print(json.dumps(export_record, indent=2))
            return 0
        print(f"no export candidates found for run: {args.run_id}", file=sys.stderr)
        return 1
    export_record = repository.persist_export(
        run_id=args.run_id,
        audience=args.audience,
        requested_precision=args.requested_precision,
        candidates=candidates,
    )
    print(json.dumps(export_record, indent=2))
    return 0


def cmd_run_summary(args: argparse.Namespace) -> int:
    run_repository = RunRepository(load_settings().db_path)
    run = run_repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    tile_count = run_repository.count_tiles(args.run_id)
    selected_tile_count = run_repository.count_selected_tiles(args.run_id)
    candidate_count = run_repository.count_candidates(args.run_id)
    top_candidate_id = run_repository.fetch_top_candidate_id(args.run_id)

    latest_export_record_id = None
    latest_export_artifact_path = None
    export_records = ExportRepository(load_settings().db_path).fetch_export_records(args.run_id)
    if export_records:
        latest = max(
            export_records,
            key=lambda r: (str(r.get("created_at") or ""), str(r["export_record_id"])),
        )
        latest_export_record_id = latest["export_record_id"]
        latest_export_artifact_path = latest.get("artifact_path")

    summary = {
        "run_id": run["run_id"],
        "status": run.get("status"),
        "aoi_hash": run.get("aoi_hash"),
        "aoi_path": run.get("aoi_path"),
        "start_date": run.get("start_date"),
        "end_date": run.get("end_date"),
        "legal_gate_decision": run.get("legal_gate", {}).get("decision"),
        "source_endpoint_id": run.get("source_endpoint_id"),
        "source_scene_manifest_hash": run.get("source_scene_manifest_hash"),
        "tile_count": tile_count,
        "selected_tile_count": selected_tile_count,
        "candidate_count": candidate_count,
        "top_candidate_id": top_candidate_id,
        "latest_export_record_id": latest_export_record_id,
        "latest_export_artifact_path": latest_export_artifact_path,
    }
    print(json.dumps(summary, indent=2))
    return 0


def _build_quote_service() -> QuoteService:
    db_path = load_settings().db_path
    return QuoteService(
        acceptance_repository=AcceptanceRepository(db_path),
        paid_repository=PaidRepository(db_path),
        review_repository=ReviewRepository(db_path),
        archive_client=Up42ArchiveClient(),
    )


def _build_order_service() -> OrderService:
    db_path = load_settings().db_path
    return OrderService(
        acceptance_repository=AcceptanceRepository(db_path),
        paid_repository=PaidRepository(db_path),
        review_repository=ReviewRepository(db_path),
        archive_client=Up42ArchiveClient(),
    )


def cmd_paid_quote_create(args: argparse.Namespace) -> int:
    quote = _build_quote_service().create_quote(
        candidate_id=args.candidate_id,
        provider_quote_id=args.provider_quote_id,
        amount=args.amount,
        credits=args.credits,
        currency=args.currency,
        eula_reference=args.eula_reference,
        project_id=args.project_id,
    )
    print(json.dumps(quote, indent=2))
    return 0


def cmd_paid_quote_show(args: argparse.Namespace) -> int:
    if args.candidate_id is None and args.provider_quote_id is None:
        print("paid quote lookup requires --candidate-id or --provider-quote-id", file=sys.stderr)
        return 1
    quote = _build_quote_service().fetch_quote(
        candidate_id=args.candidate_id,
        provider_quote_id=args.provider_quote_id,
    )
    if quote is None:
        print("paid quote not found", file=sys.stderr)
        return 1
    print(json.dumps(quote, indent=2))
    return 0


def cmd_paid_order_create(args: argparse.Namespace) -> int:
    order = _build_order_service().create_order(
        candidate_id=args.candidate_id,
        provider_quote_id=args.provider_quote_id,
        provider_order_id=args.provider_order_id,
        requested_by=args.requested_by,
    )
    print(json.dumps(order, indent=2))
    return 0


def cmd_paid_order_show(args: argparse.Namespace) -> int:
    if args.candidate_id is None and args.provider_order_id is None:
        print("paid order lookup requires --candidate-id or --provider-order-id", file=sys.stderr)
        return 1
    order = _build_order_service().fetch_order(
        candidate_id=args.candidate_id,
        provider_order_id=args.provider_order_id,
    )
    if order is None:
        print("paid order not found", file=sys.stderr)
        return 1
    print(json.dumps(order, indent=2))
    return 0


def cmd_paid_order_status(args: argparse.Namespace) -> int:
    order = _build_order_service().update_order_status(
        provider_order_id=args.provider_order_id,
        paid_status=args.paid_status,
    )
    print(json.dumps(order, indent=2))
    return 0


def _build_kpi_summary_from_args(args: argparse.Namespace) -> dict:
    repository = AcceptanceRepository(load_settings().db_path)
    run = repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        raise SystemExit(1)
    return build_kpi_summary(
        run_id=args.run_id,
        source_scene_manifest_hash=run["source_scene_manifest_hash"],
        candidate_rows=repository.fetch_candidate_rows(args.run_id),
        aoi_area_km2=args.aoi_area_km2,
        time_to_first_review_package_hours=args.time_to_first_review_package_hours,
        paid_escalation_count=repository.count_paid_escalations(args.run_id),
    )


def cmd_kpi_summary(args: argparse.Namespace) -> int:
    summary = _build_kpi_summary_from_args(args)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_acceptance_check(args: argparse.Namespace) -> int:
    baseline = _load_baseline()
    calibration_policy_id = (baseline.get("calibration_policy") or {}).get("calibration_policy_id")
    repository = AcceptanceRepository(load_settings().db_path)
    run = repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    kpi_summary = _build_kpi_summary_from_args(args)
    comparison_run_id = args.comparison_run_id or args.retuned_run_id
    reproducibility_summary = None
    stability_value = None
    if comparison_run_id is not None:
        comparison_run = repository.fetch_run(comparison_run_id)
        if comparison_run is None:
            print(f"run not found: {comparison_run_id}", file=sys.stderr)
            return 1
        reproducibility_summary = reproducibility_check(
            baseline_run=run,
            comparison_run=comparison_run,
            baseline_candidates=repository.fetch_candidate_rows(args.run_id),
            comparison_candidates=repository.fetch_candidate_rows(comparison_run_id),
        )
        stability_value = reproducibility_summary["top10_stability_rate"]
    summary = build_acceptance_summary(
        kpi_summary=kpi_summary,
        top10_stability_rate_value=stability_value,
        run_metadata=run,
        review_state_counts=repository.fetch_review_state_counts(args.run_id),
        export_audit_manifest=repository.fetch_latest_export_audit_manifest(args.run_id),
        reproducibility_summary=reproducibility_summary,
        calibration_policy_id=calibration_policy_id,
    )
    if args.output == "markdown":
        print(render_acceptance_summary_markdown(summary), end="")
    else:
        print(json.dumps(summary, indent=2))
    return 0 if summary["status"] in {"pass", "warn"} else 1


def cmd_calibration_pack(args: argparse.Namespace) -> int:
    settings = load_settings()
    baseline = _load_baseline()
    calibration_policy = baseline.get("calibration_policy")
    repository = AcceptanceRepository(settings.db_path)
    run = repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    reproducibility_summary = None
    if args.comparison_run_id is not None:
        comparison_run = repository.fetch_run(args.comparison_run_id)
        if comparison_run is None:
            print(f"run not found: {args.comparison_run_id}", file=sys.stderr)
            return 1
        reproducibility_summary = reproducibility_check(
            baseline_run=run,
            comparison_run=comparison_run,
            baseline_candidates=repository.fetch_candidate_rows(args.run_id),
            comparison_candidates=repository.fetch_candidate_rows(args.comparison_run_id),
        )
    pack = build_calibration_pack(
        run_metadata=run,
        candidate_rows=repository.fetch_candidate_rows(args.run_id),
        review_state_counts=repository.fetch_review_state_counts(args.run_id),
        export_audit_manifest=repository.fetch_latest_export_audit_manifest(args.run_id),
        paid_escalation_count=repository.count_paid_escalations(args.run_id),
        reproducibility_summary=reproducibility_summary,
        calibration_policy=calibration_policy,
        threshold_policy_source=str(settings.baseline_path),
    )
    if args.output == "markdown":
        print(render_calibration_pack_markdown(pack), end="")
    else:
        print(json.dumps(pack, indent=2))
    return 0 if pack["status"] in {"ready", "incomplete"} else 1


def cmd_calibration_label_pack(args: argparse.Namespace) -> int:
    settings = load_settings()
    baseline = _load_baseline()
    calibration_policy = baseline.get("calibration_policy")
    repository = AcceptanceRepository(settings.db_path)
    run = repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    pack = build_calibration_label_pack(
        run_metadata=run,
        candidate_rows=repository.fetch_candidate_rows(args.run_id),
        label_rows=repository.fetch_label_candidates(
            args.run_id,
            include_pending=bool(args.include_pending),
        ),
        review_state_counts=repository.fetch_review_state_counts(args.run_id),
        export_audit_manifest=repository.fetch_latest_export_audit_manifest(args.run_id),
        calibration_policy=calibration_policy,
    )
    if args.output == "markdown":
        print(render_calibration_label_pack_markdown(pack), end="")
    else:
        print(json.dumps(pack, indent=2))
    return 0 if pack["status"] in {"ready", "incomplete"} else 1


def cmd_calibration_label_manifest(args: argparse.Namespace) -> int:
    settings = load_settings()
    baseline = _load_baseline()
    calibration_policy = baseline.get("calibration_policy")
    repository = AcceptanceRepository(settings.db_path)
    run = repository.fetch_run(args.run_id)
    if run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    pack = build_calibration_label_pack(
        run_metadata=run,
        candidate_rows=repository.fetch_candidate_rows(args.run_id),
        label_rows=repository.fetch_label_candidates(
            args.run_id,
            include_pending=bool(args.include_pending),
        ),
        review_state_counts=repository.fetch_review_state_counts(args.run_id),
        export_audit_manifest=repository.fetch_latest_export_audit_manifest(args.run_id),
        calibration_policy=calibration_policy,
    )
    manifest = build_calibration_label_manifest(
        label_pack=pack,
        include_pending=bool(args.include_pending),
    )
    if args.output == "markdown":
        print(render_calibration_label_manifest_markdown(manifest), end="")
    else:
        print(json.dumps(manifest, indent=2))
    return 0 if manifest["status"] in {"ready", "incomplete"} else 1


def _build_calibration_label_payloads(
    *,
    run_id: str,
    include_pending: bool,
) -> tuple[dict, dict]:
    settings = load_settings()
    baseline = _load_baseline()
    calibration_policy = baseline.get("calibration_policy")
    repository = AcceptanceRepository(settings.db_path)
    run = repository.fetch_run(run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    pack = build_calibration_label_pack(
        run_metadata=run,
        candidate_rows=repository.fetch_candidate_rows(run_id),
        label_rows=repository.fetch_label_candidates(
            run_id,
            include_pending=include_pending,
        ),
        review_state_counts=repository.fetch_review_state_counts(run_id),
        export_audit_manifest=repository.fetch_latest_export_audit_manifest(run_id),
        calibration_policy=calibration_policy,
    )
    manifest = build_calibration_label_manifest(
        label_pack=pack,
        include_pending=include_pending,
    )
    return pack, manifest


def _render_calibration_label_export_markdown(
    *,
    manifest: dict,
    artifact_hash: str,
    files: list[str],
) -> str:
    lines = [
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
    ]
    lines.extend(f"- `{file_name}`" for file_name in files)
    lines.extend(["", "## Reasons", ""])
    lines.extend(f"- {reason}" for reason in manifest["reasons"])
    return "\n".join(lines) + "\n"


def _render_sha256sums(file_hashes: dict[str, str]) -> str:
    return "".join(f"{file_hashes[file_name]}  {file_name}\n" for file_name in sorted(file_hashes))


def _build_artifact_hash(
    *,
    run_id: str,
    include_pending: bool,
    files: list[str],
    file_hashes: dict[str, str],
) -> str:
    return _stable_hash(
        {
            "run_id": run_id,
            "include_pending": include_pending,
            "files": [
                {"name": file_name, "sha256": file_hashes[file_name]}
                for file_name in files
            ],
        }
    )


def _required_calibration_artifact_files() -> list[str]:
    return [
        "calibration_label_pack.json",
        "calibration_label_manifest.json",
        "calibration_label_manifest.md",
        "SHA256SUMS.txt",
    ]


def _render_calibration_label_verify_markdown(result: dict) -> str:
    lines = [
        "# Calibration Label Artifact Verification",
        "",
        f"- Artifact directory: `{result['artifact_dir']}`",
        f"- Status: `{result['status']}`",
        f"- Artifact hash valid: `{result['artifact_hash_valid']}`",
        f"- Label pack hash valid: `{result['label_pack_hash_valid']}`",
        f"- Label manifest hash valid: `{result['label_manifest_hash_valid']}`",
        f"- SHA256SUMS valid: `{result['sha256sums_valid']}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _render_calibration_label_register_markdown(result: dict) -> str:
    lines = [
        "# Calibration Label Artifact Registration",
        "",
        f"- Status: `{result['status']}`",
        f"- Artifact hash: `{result['artifact_hash']}`",
        f"- Run ID: `{result['run_id']}`",
        f"- Artifact status: `{result['artifact_status']}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _render_calibration_label_registry_list_markdown(result: dict) -> str:
    lines = [
        "# Calibration Label Artifact Registry",
        "",
        f"- Status: `{result['status']}`",
        f"- Artifact count: `{result['artifact_count']}`",
        "",
        "## Artifacts",
        "",
        "| Run ID | Artifact Hash | Artifact Status | Label Count | Include Pending |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for artifact in result["artifacts"]:
        lines.append(
            "| `{run_id}` | `{artifact_hash}` | `{artifact_status}` | {label_count} | `{include_pending}` |".format(
                run_id=artifact["run_id"],
                artifact_hash=artifact["artifact_hash"],
                artifact_status=artifact["artifact_status"],
                label_count=artifact["label_count"],
                include_pending=artifact["include_pending"],
            )
        )
    return "\n".join(lines) + "\n"


def _render_calibration_label_registry_export_markdown(
    result: dict,
    snapshot_hash: str,
) -> str:
    lines = [
        "# Calibration Registry Snapshot",
        "",
        f"- Status: `{result['status']}`",
        f"- Snapshot hash: `{snapshot_hash}`",
        f"- Artifact count: `{result['artifact_count']}`",
        "",
        "## Files",
        "",
    ]
    lines.extend(f"- `{file_name}`" for file_name in result["files"])
    lines.extend(["", "## Reasons", ""])
    if not result.get("reasons"):
        lines.append("- Registry snapshot exported successfully")
    else:
        lines.extend(f"- {reason}" for reason in result["reasons"])
    lines.extend([
        "",
        "## Artifacts",
        "",
        "| Run ID | Artifact Hash | Artifact Status | Label Count | Include Pending |",
        "| --- | --- | --- | ---: | --- |",
    ])
    for artifact in result["artifacts"]:
        lines.append(
            "| `{run_id}` | `{artifact_hash}` | `{artifact_status}` | {label_count} | `{include_pending}` |".format(
                run_id=artifact["run_id"],
                artifact_hash=artifact["artifact_hash"],
                artifact_status=artifact["artifact_status"],
                label_count=artifact["label_count"],
                include_pending=artifact["include_pending"],
            )
        )
    return "\n".join(lines) + "\n"


def _render_calibration_label_registry_snapshot_verify_markdown(result: dict) -> str:
    lines = [
        "# Calibration Registry Snapshot Verification",
        "",
        f"- Status: `{result['status']}`",
        f"- Snapshot hash valid: `{result['snapshot_hash_valid']}`",
        f"- SHA256SUMS valid: `{result['sha256sums_valid']}`",
        f"- Cross-check valid: `{result['snapshot_cross_checks_valid']}`",
        f"- Artifact count: `{result['artifact_count']}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _extract_artifact_hash_from_markdown(markdown: str) -> str | None:
    match = re.search(r"(?m)^- Artifact hash: `([^`]+)`\s*$", markdown)
    if match is None:
        return None
    return match.group(1)


def _canonicalize_artifact_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    canonical_lines = []
    for line in lines:
        if line.startswith("- Artifact hash: `"):
            canonical_lines.append("- Artifact hash: `<artifact_hash_excluded_from_hash_input>`")
        else:
            canonical_lines.append(line)
    return "\n".join(canonical_lines) + "\n"


def _build_snapshot_hash(
    *,
    artifact_count: int,
    artifacts: list[dict],
    files: list[str],
    file_hashes: dict[str, str],
) -> str:
    return _stable_hash(
        {
            "snapshot_type": "calibration_artifact_registry",
            "snapshot_version": 1,
            "artifact_count": artifact_count,
            "artifacts": artifacts,
            "files": [
                {"name": file_name, "sha256": file_hashes[file_name]}
                for file_name in files
            ],
        }
    )


def _recompute_snapshot_hash(
    artifact_count: int,
    artifacts: list[dict],
    files: list[str],
) -> tuple[str, dict[str, str]]:
    registry_json_payload = {
        "snapshot_type": "calibration_artifact_registry",
        "snapshot_version": 1,
        "artifact_count": artifact_count,
        "artifacts": artifacts,
        "snapshot_hash": "<snapshot_hash_excluded_from_hash_input>",
    }
    canonical_json_text = _stable_json_text(registry_json_payload)

    result_dict = {
        "status": "exported",
        "reasons": [],
        "output_dir": "",
        "artifact_count": artifact_count,
        "artifacts": artifacts,
        "files": files,
    }

    canonical_markdown = _render_calibration_label_registry_export_markdown(
        result_dict,
        snapshot_hash="<snapshot_hash_excluded_from_hash_input>",
    )

    canonical_hashes = {
        "calibration_artifact_registry.json": _sha256_text(canonical_json_text),
        "calibration_artifact_registry.md": _sha256_text(canonical_markdown),
    }
    canonical_sha256sums = _render_sha256sums(canonical_hashes)
    canonical_hashes["SHA256SUMS.txt"] = _sha256_text(canonical_sha256sums)

    snapshot_hash = _build_snapshot_hash(
        artifact_count=artifact_count,
        artifacts=artifacts,
        files=files,
        file_hashes=canonical_hashes,
    )
    return snapshot_hash, canonical_hashes


def _compute_calibration_label_pack_hash(pack: dict) -> str:
    return _stable_hash(
        {
            "run_id": pack.get("run_id"),
            "calibration_policy_id": pack.get("calibration_policy_id"),
            "latest_export_audit_manifest_hash": pack.get("latest_export_audit_manifest_hash"),
            "labels": pack.get("labels", []),
        }
    )


def _compute_calibration_label_manifest_hash(manifest: dict) -> str:
    return _stable_hash(
        {
            "manifest_type": manifest.get("manifest_type"),
            "manifest_version": manifest.get("manifest_version"),
            "run_id": manifest.get("run_id"),
            "calibration_policy_id": manifest.get("calibration_policy_id"),
            "processing_baseline_id": manifest.get("processing_baseline_id"),
            "score_formula_version": manifest.get("score_formula_version"),
            "source_scene_manifest_hash": manifest.get("source_scene_manifest_hash"),
            "latest_export_audit_manifest_hash": manifest.get("latest_export_audit_manifest_hash"),
            "include_pending": manifest.get("include_pending"),
            "label_pack_hash": manifest.get("label_pack_hash"),
            "label_ids": manifest.get("label_ids", []),
        }
    )


def _registry_verification_payload(verification: dict) -> dict:
    return {
        key: value
        for key, value in verification.items()
        if key != "artifact_dir"
    }


def _verify_calibration_label_artifact(artifact_dir: Path) -> dict:
    files = _required_calibration_artifact_files()
    reasons: list[str] = []
    file_hashes: dict[str, str] = {}
    texts: dict[str, str] = {}
    pack = None
    manifest = None
    sha256_entries: dict[str, str] = {}
    sha256sums_valid = True
    artifact_hash_valid = True
    label_pack_hash_valid = True
    label_manifest_hash_valid = True
    manifest_cross_checks_valid = True

    for file_name in files:
        path = artifact_dir / file_name
        if not path.exists():
            reasons.append(f"Missing required artifact file: {file_name}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            reasons.append(f"Artifact file is not valid UTF-8 text: {file_name}")
            continue
        texts[file_name] = text
        file_hashes[file_name] = _sha256_text(text)

    if "calibration_label_pack.json" in texts:
        try:
            pack = json.loads(texts["calibration_label_pack.json"])
            if not isinstance(pack, dict):
                reasons.append("calibration_label_pack.json must contain a JSON object")
                pack = None
                label_pack_hash_valid = False
                manifest_cross_checks_valid = False
        except json.JSONDecodeError:
            reasons.append("Artifact file is not valid JSON: calibration_label_pack.json")
            label_pack_hash_valid = False
            manifest_cross_checks_valid = False
    else:
        label_pack_hash_valid = False
        manifest_cross_checks_valid = False

    if "calibration_label_manifest.json" in texts:
        try:
            manifest = json.loads(texts["calibration_label_manifest.json"])
            if not isinstance(manifest, dict):
                reasons.append("calibration_label_manifest.json must contain a JSON object")
                manifest = None
                label_manifest_hash_valid = False
                manifest_cross_checks_valid = False
        except json.JSONDecodeError:
            reasons.append("Artifact file is not valid JSON: calibration_label_manifest.json")
            label_manifest_hash_valid = False
            manifest_cross_checks_valid = False
    else:
        label_manifest_hash_valid = False
        manifest_cross_checks_valid = False

    markdown_text = texts.get("calibration_label_manifest.md")
    sha_text = texts.get("SHA256SUMS.txt")
    required_checksum_files = {
        "calibration_label_pack.json",
        "calibration_label_manifest.json",
        "calibration_label_manifest.md",
    }

    if sha_text is None:
        sha256sums_valid = False
    else:
        for raw_line in sha_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.fullmatch(r"([0-9a-f]{64})\s{2}(.+)", line)
            if match is None:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt contains malformed line: {raw_line}")
                continue
            sha256_entries[match.group(2)] = match.group(1)
        for file_name in sorted(required_checksum_files.difference(sha256_entries)):
            sha256sums_valid = False
            reasons.append(f"SHA256SUMS.txt missing hash entry for {file_name}")
        if "SHA256SUMS.txt" in sha256_entries:
            sha256sums_valid = False
            reasons.append("SHA256SUMS.txt must not contain a self-hash line")
        for file_name in sorted(required_checksum_files.intersection(file_hashes)):
            if sha256_entries.get(file_name) != file_hashes[file_name]:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt hash mismatch for {file_name}")

    reported_artifact_hash = _extract_artifact_hash_from_markdown(markdown_text) if markdown_text else None
    if reported_artifact_hash is None:
        artifact_hash_valid = False
        reasons.append("Artifact hash line missing from calibration_label_manifest.md")

    if pack is not None:
        computed_pack_hash = _compute_calibration_label_pack_hash(pack)
        if pack.get("label_pack_hash") != computed_pack_hash:
            label_pack_hash_valid = False
            reasons.append("calibration_label_pack.json label_pack_hash does not match canonical hash")
        forbidden_coordinate_fields = {
            "lon",
            "lat",
            "longitude",
            "latitude",
            "geometry",
            "centroid",
            "bbox",
        }
        for label in pack.get("labels", []):
            for field_name in forbidden_coordinate_fields:
                if field_name in label:
                    manifest_cross_checks_valid = False
                    reasons.append(f"Label includes forbidden coordinate field: {field_name}")

    if manifest is not None:
        computed_manifest_hash = _compute_calibration_label_manifest_hash(manifest)
        if manifest.get("label_manifest_hash") != computed_manifest_hash:
            label_manifest_hash_valid = False
            reasons.append("calibration_label_manifest.json label_manifest_hash does not match canonical hash")

    if pack is not None and manifest is not None:
        pack_label_ids = [str(label["candidate_id"]) for label in pack.get("labels", [])]
        if manifest.get("label_pack_hash") != pack.get("label_pack_hash"):
            manifest_cross_checks_valid = False
            reasons.append("Manifest label_pack_hash does not match pack label_pack_hash")
        if manifest.get("run_id") != pack.get("run_id"):
            manifest_cross_checks_valid = False
            reasons.append("Manifest run_id does not match pack run_id")
        if manifest.get("status") != pack.get("status"):
            manifest_cross_checks_valid = False
            reasons.append("Manifest status does not match pack status")
        if [str(label_id) for label_id in manifest.get("label_ids", [])] != pack_label_ids:
            manifest_cross_checks_valid = False
            reasons.append("Manifest label_ids do not match pack label order")
        if manifest.get("label_count") != len(manifest.get("label_ids", [])):
            manifest_cross_checks_valid = False
            reasons.append("Manifest label_count does not match label_ids count")

    if reported_artifact_hash is not None and all(file_name in texts for file_name in files):
        canonical_hashes = {
            "calibration_label_pack.json": file_hashes["calibration_label_pack.json"],
            "calibration_label_manifest.json": file_hashes["calibration_label_manifest.json"],
            "calibration_label_manifest.md": _sha256_text(
                _canonicalize_artifact_markdown(markdown_text)
            ),
        }
        canonical_sha = _render_sha256sums(canonical_hashes)
        canonical_hashes["SHA256SUMS.txt"] = _sha256_text(canonical_sha)
        computed_artifact_hash = _build_artifact_hash(
            run_id=(
                str(manifest.get("run_id"))
                if manifest is not None
                else str(pack.get("run_id"))
                if pack is not None
                else ""
            ),
            include_pending=bool(manifest.get("include_pending")) if manifest is not None else False,
            files=files,
            file_hashes=canonical_hashes,
        )
        if reported_artifact_hash != computed_artifact_hash:
            artifact_hash_valid = False
            reasons.append("Artifact hash does not match canonical artifact hash")

    if not reasons:
        reasons = ["Calibration label artifact is valid"]

    status = (
        "valid"
        if (
            sha256sums_valid
            and artifact_hash_valid
            and label_pack_hash_valid
            and label_manifest_hash_valid
            and manifest_cross_checks_valid
            and all(file_name in texts for file_name in files)
        )
        else "invalid"
    )
    if status == "valid":
        reasons = ["Calibration label artifact is valid"]

    run_id = None
    if manifest is not None:
        run_id = manifest.get("run_id")
    elif pack is not None:
        run_id = pack.get("run_id")

    return {
        "status": status,
        "reasons": reasons,
        "artifact_dir": str(artifact_dir),
        "run_id": run_id,
        "artifact_status": (
            manifest.get("status")
            if manifest is not None
            else pack.get("status")
            if pack is not None
            else None
        ),
        "label_pack_hash": pack.get("label_pack_hash") if pack is not None else None,
        "label_manifest_hash": manifest.get("label_manifest_hash") if manifest is not None else None,
        "artifact_hash": reported_artifact_hash,
        "label_count": (
            manifest.get("label_count")
            if manifest is not None
            else len(pack.get("labels", []))
            if pack is not None
            else None
        ),
        "include_pending": bool(manifest.get("include_pending")) if manifest is not None else False,
        "files": files,
        "file_hashes": file_hashes,
        "sha256sums_valid": sha256sums_valid,
        "artifact_hash_valid": artifact_hash_valid,
        "label_pack_hash_valid": label_pack_hash_valid,
        "label_manifest_hash_valid": label_manifest_hash_valid,
        "manifest_cross_checks_valid": manifest_cross_checks_valid,
    }


def _compute_expected_final_snapshot_files(
    artifact_count: int,
    artifacts: list[dict],
    files: list[str],
    snapshot_hash: str,
) -> tuple[str, str, str]:
    registry_json_payload = {
        "snapshot_type": "calibration_artifact_registry",
        "snapshot_version": 1,
        "artifact_count": artifact_count,
        "artifacts": artifacts,
        "snapshot_hash": snapshot_hash,
    }
    expected_json_text = _stable_json_text(registry_json_payload)

    result_dict = {
        "status": "exported",
        "reasons": [],
        "output_dir": "",
        "artifact_count": artifact_count,
        "artifacts": artifacts,
        "files": files,
    }
    expected_md_text = _render_calibration_label_registry_export_markdown(
        result_dict,
        snapshot_hash=snapshot_hash,
    )

    expected_hashes = {
        "calibration_artifact_registry.json": _sha256_text(expected_json_text),
        "calibration_artifact_registry.md": _sha256_text(expected_md_text),
    }
    expected_sha256sums = _render_sha256sums(expected_hashes)
    return expected_json_text, expected_md_text, expected_sha256sums


def _verify_calibration_registry_snapshot(snapshot_dir: Path) -> dict:
    files = [
        "calibration_artifact_registry.json",
        "calibration_artifact_registry.md",
        "SHA256SUMS.txt",
    ]
    reasons: list[str] = []
    file_hashes: dict[str, str] = {}
    texts: dict[str, str] = {}

    for file_name in files:
        path = snapshot_dir / file_name
        if not path.exists():
            reasons.append(f"Missing required snapshot file: {file_name}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            reasons.append(f"Snapshot file is not valid UTF-8 text: {file_name}")
            continue
        texts[file_name] = text
        file_hashes[file_name] = _sha256_text(text)

    registry_json = None
    if "calibration_artifact_registry.json" in texts:
        try:
            registry_json = json.loads(texts["calibration_artifact_registry.json"])
            if not isinstance(registry_json, dict):
                reasons.append("calibration_artifact_registry.json must contain a JSON object")
                registry_json = None
        except json.JSONDecodeError:
            reasons.append("Snapshot file is not valid JSON: calibration_artifact_registry.json")

    artifact_count = 0
    artifacts: list[dict] = []
    json_structurally_valid = registry_json is not None

    if registry_json is not None:
        if registry_json.get("snapshot_type") != "calibration_artifact_registry":
            reasons.append("JSON snapshot_type must be calibration_artifact_registry")
        if registry_json.get("snapshot_version") != 1:
            reasons.append("JSON snapshot_version must be 1")

        raw_count = registry_json.get("artifact_count")
        if not isinstance(raw_count, int):
            reasons.append(
                f"JSON artifact_count must be an integer, got {type(raw_count).__name__}"
            )
            json_structurally_valid = False
        else:
            artifact_count = raw_count

        raw_artifacts = registry_json.get("artifacts")
        if not isinstance(raw_artifacts, list):
            reasons.append(
                f"JSON artifacts must be a list, got {type(raw_artifacts).__name__}"
            )
            json_structurally_valid = False
        else:
            artifacts = raw_artifacts

        if json_structurally_valid and artifact_count != len(artifacts):
            reasons.append(
                f"JSON artifact_count ({artifact_count}) does not match artifacts length ({len(artifacts)})"
            )

        if json_structurally_valid:
            all_artifacts_are_objects = True
            for i, artifact in enumerate(artifacts):
                if not isinstance(artifact, dict):
                    reasons.append(
                        f"Artifact {i} must be a JSON object, got {type(artifact).__name__}"
                    )
                    all_artifacts_are_objects = False
            if not all_artifacts_are_objects:
                json_structurally_valid = False

        if json_structurally_valid:
            expected_sort = sorted(
                artifacts,
                key=lambda a: (a.get("run_id", ""), a.get("artifact_hash", "")),
            )
            if artifacts != expected_sort:
                reasons.append(
                    "JSON artifacts must be sorted by run_id ascending, then artifact_hash ascending"
                )

            required_artifact_fields = {
                "artifact_hash",
                "run_id",
                "artifact_status",
                "label_pack_hash",
                "label_manifest_hash",
                "label_count",
                "include_pending",
                "files",
                "file_hashes",
            }
            valid_statuses = {"ready", "incomplete", "fail"}
            forbidden_label_fields = {"labels", "label_ids"}
            forbidden_coordinate_fields = {
                "lon",
                "lat",
                "longitude",
                "latitude",
                "geometry",
                "centroid",
                "bbox",
            }

            for i, artifact in enumerate(artifacts):
                missing = required_artifact_fields - set(artifact.keys())
                if missing:
                    reasons.append(
                        f"Artifact {i} missing required fields: {', '.join(sorted(missing))}"
                    )

                status = artifact.get("artifact_status")
                if status not in valid_statuses:
                    reasons.append(
                        f"Artifact {i} artifact_status must be ready, incomplete, or fail, got {status}"
                    )

                for field in forbidden_label_fields:
                    if field in artifact:
                        reasons.append(
                            f"Artifact {i} must not contain full label payload field: {field}"
                        )

                for field in forbidden_coordinate_fields:
                    if field in artifact:
                        reasons.append(
                            f"Artifact {i} must not contain coordinate field: {field}"
                        )

    sha256sums_valid = True
    sha256_entries: dict[str, str] = {}
    if "SHA256SUMS.txt" in texts:
        for raw_line in texts["SHA256SUMS.txt"].splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.fullmatch(r"([0-9a-f]{64})\s{2}(.+)", line)
            if match is None:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt contains malformed line: {raw_line}")
                continue
            sha256_entries[match.group(2)] = match.group(1)

        required_checksum_files = {
            "calibration_artifact_registry.json",
            "calibration_artifact_registry.md",
        }
        for file_name in sorted(required_checksum_files.difference(sha256_entries)):
            sha256sums_valid = False
            reasons.append(f"SHA256SUMS.txt missing hash entry for {file_name}")

        if "SHA256SUMS.txt" in sha256_entries:
            sha256sums_valid = False
            reasons.append("SHA256SUMS.txt must not contain a self-hash line")

        for file_name in sorted(required_checksum_files.intersection(file_hashes)):
            if sha256_entries.get(file_name) != file_hashes[file_name]:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt hash mismatch for {file_name}")
    else:
        sha256sums_valid = False

    md_text = texts.get("calibration_artifact_registry.md", "")
    md_snapshot_hash = None
    md_valid = True
    if md_text:
        required_md_sections = [
            "# Calibration Registry Snapshot",
            "Snapshot hash:",
            "Artifact count:",
            "## Files",
            "## Reasons",
            "## Artifacts",
        ]
        for section in required_md_sections:
            if section not in md_text:
                md_valid = False
                reasons.append(f"Markdown missing required section: {section}")

        match = re.search(r"(?m)^- Snapshot hash: `([^`]+)`\s*$", md_text)
        if match:
            md_snapshot_hash = match.group(1)
        else:
            md_valid = False
            reasons.append("Markdown missing Snapshot hash line")

    snapshot_hash_valid = True
    snapshot_cross_checks_valid = True
    canonical_files_valid = True
    reported_snapshot_hash = None

    if registry_json is not None:
        reported_snapshot_hash = registry_json.get("snapshot_hash")
        if not reported_snapshot_hash:
            snapshot_hash_valid = False
            reasons.append("JSON missing snapshot_hash")
        elif not json_structurally_valid:
            snapshot_hash_valid = False
            reasons.append("Cannot validate snapshot_hash because JSON structure is invalid")
        else:
            try:
                recomputed_hash, _ = _recompute_snapshot_hash(
                    artifact_count=artifact_count,
                    artifacts=artifacts,
                    files=files,
                )
                if reported_snapshot_hash != recomputed_hash:
                    snapshot_hash_valid = False
                    reasons.append("snapshot_hash does not match recalculated snapshot hash")
                else:
                    expected_json_text, expected_md_text, expected_sha256sums = (
                        _compute_expected_final_snapshot_files(
                            artifact_count=artifact_count,
                            artifacts=artifacts,
                            files=files,
                            snapshot_hash=reported_snapshot_hash,
                        )
                    )
                    if texts.get("calibration_artifact_registry.json") != expected_json_text:
                        canonical_files_valid = False
                        reasons.append(
                            "calibration_artifact_registry.json does not match canonical final content"
                        )
                    if texts.get("calibration_artifact_registry.md") != expected_md_text:
                        canonical_files_valid = False
                        reasons.append(
                            "calibration_artifact_registry.md does not match canonical final content"
                        )
                    if texts.get("SHA256SUMS.txt") != expected_sha256sums:
                        canonical_files_valid = False
                        reasons.append(
                            "SHA256SUMS.txt does not match canonical final content"
                        )
            except Exception as exc:
                snapshot_hash_valid = False
                reasons.append(f"Failed to recalculate snapshot hash: {exc}")

            if md_snapshot_hash is not None and md_snapshot_hash != reported_snapshot_hash:
                snapshot_cross_checks_valid = False
                reasons.append("Markdown snapshot hash does not match JSON snapshot_hash")

    status = (
        "valid"
        if (
            not reasons
            and sha256sums_valid
            and snapshot_hash_valid
            and snapshot_cross_checks_valid
            and canonical_files_valid
            and registry_json is not None
            and "calibration_artifact_registry.md" in texts
            and "SHA256SUMS.txt" in texts
        )
        else "invalid"
    )
    if status == "valid":
        reasons = ["Calibration registry snapshot is valid"]

    return {
        "status": status,
        "reasons": reasons,
        "snapshot_dir": str(snapshot_dir),
        "artifact_count": artifact_count,
        "snapshot_hash": reported_snapshot_hash,
        "files": files,
        "file_hashes": file_hashes,
        "sha256sums_valid": sha256sums_valid,
        "snapshot_hash_valid": snapshot_hash_valid,
        "snapshot_cross_checks_valid": snapshot_cross_checks_valid,
    }


def cmd_calibration_label_export(args: argparse.Namespace) -> int:
    pack, manifest = _build_calibration_label_payloads(
        run_id=args.run_id,
        include_pending=bool(args.include_pending),
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [
        "calibration_label_pack.json",
        "calibration_label_manifest.json",
        "calibration_label_manifest.md",
        "SHA256SUMS.txt",
    ]
    pack_json = _stable_json_text(pack)
    manifest_json = _stable_json_text(manifest)
    core_hashes = {
        "calibration_label_pack.json": _sha256_text(pack_json),
        "calibration_label_manifest.json": _sha256_text(manifest_json),
    }

    # Use canonical markdown/SHA inputs for artifact hashing to avoid circular self-reference.
    canonical_markdown = _render_calibration_label_export_markdown(
        manifest=manifest,
        artifact_hash="<artifact_hash_excluded_from_hash_input>",
        files=files,
    )
    canonical_hashes = {
        **core_hashes,
        "calibration_label_manifest.md": _sha256_text(canonical_markdown),
    }
    canonical_sha256sums = _render_sha256sums(canonical_hashes)
    canonical_hashes["SHA256SUMS.txt"] = _sha256_text(canonical_sha256sums)
    artifact_hash = _build_artifact_hash(
        run_id=manifest["run_id"],
        include_pending=bool(args.include_pending),
        files=files,
        file_hashes=canonical_hashes,
    )

    markdown = _render_calibration_label_export_markdown(
        manifest=manifest,
        artifact_hash=artifact_hash,
        files=files,
    )
    file_hashes = {
        **core_hashes,
        "calibration_label_manifest.md": _sha256_text(markdown),
    }
    sha256sums = _render_sha256sums(file_hashes)
    file_hashes["SHA256SUMS.txt"] = _sha256_text(sha256sums)

    file_contents = {
        "calibration_label_pack.json": pack_json,
        "calibration_label_manifest.json": manifest_json,
        "calibration_label_manifest.md": markdown,
        "SHA256SUMS.txt": sha256sums,
    }
    for file_name, content in file_contents.items():
        (output_dir / file_name).write_text(content, encoding="utf-8", newline="\n")

    result = {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "reasons": list(manifest["reasons"]),
        "output_dir": str(output_dir),
        "include_pending": bool(args.include_pending),
        "label_pack_hash": manifest["label_pack_hash"],
        "label_manifest_hash": manifest["label_manifest_hash"],
        "artifact_hash": artifact_hash,
        "files": files,
        "file_hashes": file_hashes,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"ready", "incomplete"} else 1


def cmd_calibration_label_verify(args: argparse.Namespace) -> int:
    result = _verify_calibration_label_artifact(Path(args.artifact_dir))
    if args.output == "markdown":
        print(_render_calibration_label_verify_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "valid" else 1


def cmd_calibration_label_register(args: argparse.Namespace) -> int:
    verification = _verify_calibration_label_artifact(Path(args.artifact_dir))
    if verification["status"] != "valid":
        result = {
            "status": "invalid",
            "reasons": list(verification["reasons"]),
            "artifact_hash": verification["artifact_hash"],
            "run_id": verification["run_id"],
            "artifact_status": verification["artifact_status"],
            "label_pack_hash": verification["label_pack_hash"],
            "label_manifest_hash": verification["label_manifest_hash"],
            "label_count": verification["label_count"],
            "include_pending": verification["include_pending"],
            "files": verification["files"],
            "file_hashes": verification["file_hashes"],
            "registry_record": None,
        }
        if args.output == "markdown":
            print(_render_calibration_label_register_markdown(result), end="")
        else:
            print(json.dumps(result, indent=2))
        return 1

    repository = CalibrationArtifactRepository(load_settings().db_path)
    existing = repository.fetch_artifact(verification["artifact_hash"])
    registry_record = existing
    status = "already_registered"
    reasons = ["Calibration label artifact already registered"]
    if existing is None:
        registry_record = repository.save_artifact(
            {
                "artifact_hash": verification["artifact_hash"],
                "run_id": verification["run_id"],
                "artifact_status": verification["artifact_status"],
                "label_pack_hash": verification["label_pack_hash"],
                "label_manifest_hash": verification["label_manifest_hash"],
                "label_count": verification["label_count"],
                "include_pending": verification["include_pending"],
                "files": verification["files"],
                "file_hashes": verification["file_hashes"],
                "verification": _registry_verification_payload(verification),
            }
        )
        status = "registered"
        reasons = ["Calibration label artifact registered"]

    result = {
        "status": status,
        "reasons": reasons,
        "artifact_hash": verification["artifact_hash"],
        "run_id": verification["run_id"],
        "artifact_status": verification["artifact_status"],
        "label_pack_hash": verification["label_pack_hash"],
        "label_manifest_hash": verification["label_manifest_hash"],
        "label_count": verification["label_count"],
        "include_pending": verification["include_pending"],
        "files": verification["files"],
        "file_hashes": verification["file_hashes"],
        "registry_record": registry_record,
    }
    if args.output == "markdown":
        print(_render_calibration_label_register_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_calibration_label_registry_list(args: argparse.Namespace) -> int:
    artifacts = CalibrationArtifactRepository(load_settings().db_path).list_artifacts()
    result = {
        "status": "ok",
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "artifact_hash": artifact["artifact_hash"],
                "run_id": artifact["run_id"],
                "artifact_status": artifact["artifact_status"],
                "label_pack_hash": artifact["label_pack_hash"],
                "label_manifest_hash": artifact["label_manifest_hash"],
                "label_count": artifact["label_count"],
                "include_pending": artifact["include_pending"],
                "files": artifact["files"],
                "file_hashes": artifact["file_hashes"],
            }
            for artifact in artifacts
        ],
    }
    if args.output == "markdown":
        print(_render_calibration_label_registry_list_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_calibration_label_registry_export(args: argparse.Namespace) -> int:
    artifacts = CalibrationArtifactRepository(load_settings().db_path).list_artifacts()
    artifacts.sort(key=lambda a: (a["run_id"], a["artifact_hash"]))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [
        "calibration_artifact_registry.json",
        "calibration_artifact_registry.md",
        "SHA256SUMS.txt",
    ]

    registry_json_payload = {
        "snapshot_type": "calibration_artifact_registry",
        "snapshot_version": 1,
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "artifact_hash": a["artifact_hash"],
                "run_id": a["run_id"],
                "artifact_status": a["artifact_status"],
                "label_pack_hash": a["label_pack_hash"],
                "label_manifest_hash": a["label_manifest_hash"],
                "label_count": a["label_count"],
                "include_pending": a["include_pending"],
                "files": a["files"],
                "file_hashes": a["file_hashes"],
            }
            for a in artifacts
        ],
        "snapshot_hash": "<snapshot_hash_excluded_from_hash_input>",
    }

    canonical_json_text = _stable_json_text(registry_json_payload)
    core_hashes = {
        "calibration_artifact_registry.json": _sha256_text(canonical_json_text),
    }

    result_dict = {
        "status": "exported",
        "reasons": [],
        "output_dir": str(output_dir),
        "artifact_count": len(artifacts),
        "artifacts": registry_json_payload["artifacts"],
        "files": files,
    }

    canonical_markdown = _render_calibration_label_registry_export_markdown(
        result_dict,
        snapshot_hash="<snapshot_hash_excluded_from_hash_input>",
    )
    canonical_hashes = {
        **core_hashes,
        "calibration_artifact_registry.md": _sha256_text(canonical_markdown),
    }
    canonical_sha256sums = _render_sha256sums(canonical_hashes)
    canonical_hashes["SHA256SUMS.txt"] = _sha256_text(canonical_sha256sums)

    snapshot_hash = _build_snapshot_hash(
        artifact_count=len(artifacts),
        artifacts=registry_json_payload["artifacts"],
        files=files,
        file_hashes=canonical_hashes,
    )

    registry_json_payload["snapshot_hash"] = snapshot_hash
    final_json_text = _stable_json_text(registry_json_payload)
    
    final_markdown = _render_calibration_label_registry_export_markdown(
        result_dict,
        snapshot_hash=snapshot_hash,
    )
    
    file_hashes = {
        "calibration_artifact_registry.json": _sha256_text(final_json_text),
        "calibration_artifact_registry.md": _sha256_text(final_markdown),
    }
    final_sha256sums = _render_sha256sums(file_hashes)
    file_hashes["SHA256SUMS.txt"] = _sha256_text(final_sha256sums)

    file_contents = {
        "calibration_artifact_registry.json": final_json_text,
        "calibration_artifact_registry.md": final_markdown,
        "SHA256SUMS.txt": final_sha256sums,
    }
    for file_name, content in file_contents.items():
        (output_dir / file_name).write_text(content, encoding="utf-8", newline="\n")

    result = {
        "status": "exported",
        "reasons": [],
        "output_dir": str(output_dir),
        "artifact_count": len(artifacts),
        "snapshot_hash": snapshot_hash,
        "files": files,
        "file_hashes": file_hashes,
    }
    
    if args.output == "markdown":
        print(final_markdown, end="")
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_calibration_label_registry_snapshot_verify(args: argparse.Namespace) -> int:
    result = _verify_calibration_registry_snapshot(Path(args.snapshot_dir))
    if args.output == "markdown":
        print(_render_calibration_label_registry_snapshot_verify_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "valid" else 1


_COMPARABLE_ARTIFACT_FIELDS = {
    "artifact_hash",
    "run_id",
    "artifact_status",
    "label_pack_hash",
    "label_manifest_hash",
    "label_count",
    "include_pending",
    "files",
    "file_hashes",
}


def _artifact_identity(artifact: dict) -> dict:
    return {k: artifact[k] for k in _COMPARABLE_ARTIFACT_FIELDS}


def _compute_diff_hash(
    before_snapshot_hash: str | None,
    after_snapshot_hash: str | None,
    added: list[dict],
    removed: list[dict],
    changed: list[dict],
    unchanged: list[dict],
) -> str:
    return _stable_hash(
        {
            "before_snapshot_hash": before_snapshot_hash,
            "after_snapshot_hash": after_snapshot_hash,
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged,
        }
    )


def _render_calibration_label_registry_snapshot_diff_export_stdout_markdown(result: dict) -> str:
    lines = [
        "# Calibration Registry Snapshot Diff Export",
        "",
        f"- Status: `{result['status']}`",
        f"- Output directory: `{result.get('output_dir', '')}`",
        f"- Before snapshot directory: `{result.get('before_snapshot_dir', '')}`",
        f"- After snapshot directory: `{result.get('after_snapshot_dir', '')}`",
        f"- Diff hash: `{result.get('diff_hash', '')}`",
        f"- Before snapshot hash: `{result.get('before_snapshot_hash', '')}`",
        f"- After snapshot hash: `{result.get('after_snapshot_hash', '')}`",
        f"- Added: `{result['added_count']}`",
        f"- Removed: `{result['removed_count']}`",
        f"- Changed: `{result['changed_count']}`",
        f"- Unchanged: `{result['unchanged_count']}`",
        "",
        "## Files",
        "",
    ]
    for file_name in result.get("files", []):
        lines.append(f"- `{file_name}`")
    lines.extend(["", "## Reasons", ""])
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _render_calibration_label_registry_snapshot_diff_markdown(result: dict, files: list[str] | None = None) -> str:
    lines = [
        "# Calibration Registry Snapshot Diff",
        "",
        f"- Status: `{result['status']}`",
        f"- Diff hash: `{result['diff_hash']}`",
        f"- Before snapshot hash: `{result['before_snapshot_hash']}`",
        f"- After snapshot hash: `{result['after_snapshot_hash']}`",
        f"- Added: `{result['added_count']}`",
        f"- Removed: `{result['removed_count']}`",
        f"- Changed: `{result['changed_count']}`",
        f"- Unchanged: `{result['unchanged_count']}`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in result["reasons"])

    if files is not None:
        lines.extend(["", "## Files", ""])
        for file_name in files:
            lines.append(f"- `{file_name}`")

    sections = [
        ("## Added Artifacts", result["added"]),
        ("## Removed Artifacts", result["removed"]),
        ("## Changed Artifacts", result["changed"]),
        ("## Unchanged Artifacts", result["unchanged"]),
    ]
    for header, rows in sections:
        lines.extend(["", header, ""])
        if not rows:
            lines.append("- None")
            continue
        lines.append("| Run ID | Artifact Hash | Status | Label Count | Include Pending |")
        lines.append("| --- | --- | --- | ---: | --- |")
        for row in rows:
            if "before" in row and "after" in row:
                run_id = row["after"]["run_id"]
                artifact_hash = row["artifact_hash"]
                status = row["after"]["artifact_status"]
                label_count = row["after"]["label_count"]
                include_pending = row["after"]["include_pending"]
            else:
                run_id = row["run_id"]
                artifact_hash = row["artifact_hash"]
                status = row["artifact_status"]
                label_count = row["label_count"]
                include_pending = row["include_pending"]
            lines.append(
                "| `{run_id}` | `{artifact_hash}` | `{status}` | {label_count} | `{include_pending}` |".format(
                    run_id=run_id,
                    artifact_hash=artifact_hash,
                    status=status,
                    label_count=label_count,
                    include_pending=include_pending,
                )
            )
    return "\n".join(lines) + "\n"


def _diff_calibration_registry_snapshots(
    before_dir: Path,
    after_dir: Path,
) -> dict:
    before_verify = _verify_calibration_registry_snapshot(before_dir)
    after_verify = _verify_calibration_registry_snapshot(after_dir)

    reasons: list[str] = []
    before_valid = before_verify["status"] == "valid"
    after_valid = after_verify["status"] == "valid"

    if not before_valid:
        reasons.append(f"Before snapshot is invalid: {before_dir}")
        reasons.extend(before_verify["reasons"])
    if not after_valid:
        reasons.append(f"After snapshot is invalid: {after_dir}")
        reasons.extend(after_verify["reasons"])

    if not before_valid or not after_valid:
        return {
            "status": "invalid",
            "reasons": reasons,
            "before_snapshot_dir": str(before_dir),
            "after_snapshot_dir": str(after_dir),
            "before_snapshot_hash": before_verify.get("snapshot_hash"),
            "after_snapshot_hash": after_verify.get("snapshot_hash"),
            "before_artifact_count": before_verify.get("artifact_count", 0),
            "after_artifact_count": after_verify.get("artifact_count", 0),
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "diff_hash": None,
            "added": [],
            "removed": [],
            "changed": [],
            "unchanged": [],
            "before_valid": before_valid,
            "after_valid": after_valid,
        }

    before_json = json.loads((before_dir / "calibration_artifact_registry.json").read_text(encoding="utf-8"))
    after_json = json.loads((after_dir / "calibration_artifact_registry.json").read_text(encoding="utf-8"))

    before_artifacts = {a["artifact_hash"]: a for a in before_json.get("artifacts", [])}
    after_artifacts = {a["artifact_hash"]: a for a in after_json.get("artifacts", [])}

    added: list[dict] = []
    removed: list[dict] = []
    changed: list[dict] = []
    unchanged: list[dict] = []

    for artifact_hash, after_artifact in after_artifacts.items():
        before_artifact = before_artifacts.get(artifact_hash)
        if before_artifact is None:
            added.append({
                "artifact_hash": artifact_hash,
                "run_id": after_artifact["run_id"],
                "artifact_status": after_artifact["artifact_status"],
                "label_count": after_artifact["label_count"],
                "include_pending": after_artifact["include_pending"],
            })
        else:
            if _artifact_identity(before_artifact) == _artifact_identity(after_artifact):
                unchanged.append({
                    "artifact_hash": artifact_hash,
                    "run_id": after_artifact["run_id"],
                    "artifact_status": after_artifact["artifact_status"],
                    "label_count": after_artifact["label_count"],
                    "include_pending": after_artifact["include_pending"],
                })
            else:
                changed_fields = sorted(
                    k for k in _COMPARABLE_ARTIFACT_FIELDS
                    if before_artifact.get(k) != after_artifact.get(k)
                )
                changed.append({
                    "artifact_hash": artifact_hash,
                    "before": {
                        "run_id": before_artifact["run_id"],
                        "artifact_status": before_artifact["artifact_status"],
                        "label_pack_hash": before_artifact["label_pack_hash"],
                        "label_manifest_hash": before_artifact["label_manifest_hash"],
                        "label_count": before_artifact["label_count"],
                        "include_pending": before_artifact["include_pending"],
                        "files": before_artifact["files"],
                        "file_hashes": before_artifact["file_hashes"],
                    },
                    "after": {
                        "run_id": after_artifact["run_id"],
                        "artifact_status": after_artifact["artifact_status"],
                        "label_pack_hash": after_artifact["label_pack_hash"],
                        "label_manifest_hash": after_artifact["label_manifest_hash"],
                        "label_count": after_artifact["label_count"],
                        "include_pending": after_artifact["include_pending"],
                        "files": after_artifact["files"],
                        "file_hashes": after_artifact["file_hashes"],
                    },
                    "changed_fields": changed_fields,
                })

    for artifact_hash, before_artifact in before_artifacts.items():
        if artifact_hash not in after_artifacts:
            removed.append({
                "artifact_hash": artifact_hash,
                "run_id": before_artifact["run_id"],
                "artifact_status": before_artifact["artifact_status"],
                "label_count": before_artifact["label_count"],
                "include_pending": before_artifact["include_pending"],
            })

    sort_key = lambda a: (a.get("run_id", ""), a.get("artifact_hash", ""))
    added.sort(key=sort_key)
    removed.sort(key=sort_key)
    unchanged.sort(key=sort_key)
    changed.sort(key=lambda a: (a["after"]["run_id"], a["artifact_hash"]))

    before_snapshot_hash = before_json.get("snapshot_hash")
    after_snapshot_hash = after_json.get("snapshot_hash")

    diff_hash = _compute_diff_hash(
        before_snapshot_hash=before_snapshot_hash,
        after_snapshot_hash=after_snapshot_hash,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
    )

    reasons = ["Snapshots compared successfully"]

    return {
        "status": "compared",
        "reasons": reasons,
        "before_snapshot_dir": str(before_dir),
        "after_snapshot_dir": str(after_dir),
        "before_snapshot_hash": before_snapshot_hash,
        "after_snapshot_hash": after_snapshot_hash,
        "before_artifact_count": before_verify["artifact_count"],
        "after_artifact_count": after_verify["artifact_count"],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
        "diff_hash": diff_hash,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
        "before_valid": before_valid,
        "after_valid": after_valid,
    }


def cmd_calibration_label_registry_snapshot_diff(args: argparse.Namespace) -> int:
    result = _diff_calibration_registry_snapshots(
        Path(args.before_snapshot_dir),
        Path(args.after_snapshot_dir),
    )
    if args.output == "markdown":
        print(_render_calibration_label_registry_snapshot_diff_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "compared" else 1


def cmd_calibration_label_registry_snapshot_diff_export(args: argparse.Namespace) -> int:
    before_dir = Path(args.before_snapshot_dir)
    after_dir = Path(args.after_snapshot_dir)
    output_dir = Path(args.output_dir)

    if output_dir.exists() and any(output_dir.iterdir()) and not getattr(args, "overwrite", False):
        result = {
            "status": "invalid",
            "reasons": [f"Output directory is not empty: {output_dir}"],
            "output_dir": str(output_dir),
            "before_snapshot_dir": str(before_dir),
            "after_snapshot_dir": str(after_dir),
            "before_snapshot_hash": None,
            "after_snapshot_hash": None,
            "before_artifact_count": 0,
            "after_artifact_count": 0,
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "diff_hash": None,
            "files": [],
            "file_hashes": {},
            "before_valid": True,
            "after_valid": True,
        }
        if args.output == "markdown":
            print(_render_calibration_label_registry_snapshot_diff_export_stdout_markdown(result), end="")
        else:
            print(json.dumps(result, indent=2))
        return 1

    diff_result = _diff_calibration_registry_snapshots(before_dir, after_dir)

    if diff_result["status"] != "compared":
        result = {
            "status": "invalid",
            "reasons": diff_result["reasons"],
            "output_dir": str(output_dir),
            "before_snapshot_dir": str(before_dir),
            "after_snapshot_dir": str(after_dir),
            "before_snapshot_hash": diff_result.get("before_snapshot_hash"),
            "after_snapshot_hash": diff_result.get("after_snapshot_hash"),
            "before_artifact_count": diff_result["before_artifact_count"],
            "after_artifact_count": diff_result["after_artifact_count"],
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "unchanged_count": 0,
            "diff_hash": None,
            "files": [],
            "file_hashes": {},
            "before_valid": diff_result["before_valid"],
            "after_valid": diff_result["after_valid"],
        }
        if args.output == "markdown":
            print(_render_calibration_label_registry_snapshot_diff_export_stdout_markdown(result), end="")
        else:
            print(json.dumps(result, indent=2))
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    evidence_files = [
        "calibration_registry_snapshot_diff.json",
        "calibration_registry_snapshot_diff.md",
        "SHA256SUMS.txt",
    ]

    canonical_file_hashes = {
        "calibration_registry_snapshot_diff.json": "<file_hash_excluded_from_hash_input>",
        "calibration_registry_snapshot_diff.md": "<file_hash_excluded_from_hash_input>",
        "SHA256SUMS.txt": "<file_hash_excluded_from_hash_input>",
    }

    canonical_json_payload = {
        "snapshot_diff_type": "calibration_registry_snapshot_diff",
        "snapshot_diff_version": 1,
        "status": "compared",
        "reasons": diff_result["reasons"],
        "before_snapshot_hash": diff_result["before_snapshot_hash"],
        "after_snapshot_hash": diff_result["after_snapshot_hash"],
        "before_artifact_count": diff_result["before_artifact_count"],
        "after_artifact_count": diff_result["after_artifact_count"],
        "added_count": diff_result["added_count"],
        "removed_count": diff_result["removed_count"],
        "changed_count": diff_result["changed_count"],
        "unchanged_count": diff_result["unchanged_count"],
        "diff_hash": diff_result["diff_hash"],
        "added": diff_result["added"],
        "removed": diff_result["removed"],
        "changed": diff_result["changed"],
        "unchanged": diff_result["unchanged"],
        "before_valid": diff_result["before_valid"],
        "after_valid": diff_result["after_valid"],
        "files": evidence_files,
        "file_hashes": canonical_file_hashes,
    }

    canonical_json_text = _stable_json_text(canonical_json_payload)
    canonical_json_hash = _sha256_text(canonical_json_text)

    canonical_md_text = _render_calibration_label_registry_snapshot_diff_markdown(diff_result, files=evidence_files)
    canonical_md_hash = _sha256_text(canonical_md_text)

    canonical_sums_hashes = {
        "calibration_registry_snapshot_diff.json": canonical_json_hash,
        "calibration_registry_snapshot_diff.md": canonical_md_hash,
    }
    canonical_sha256sums = _render_sha256sums(canonical_sums_hashes)
    canonical_sums_hash = _sha256_text(canonical_sha256sums)

    final_json_payload = {
        **canonical_json_payload,
        "file_hashes": {
            "calibration_registry_snapshot_diff.json": canonical_json_hash,
            "calibration_registry_snapshot_diff.md": canonical_md_hash,
            "SHA256SUMS.txt": canonical_sums_hash,
        },
    }
    final_json_text = _stable_json_text(final_json_payload)
    final_md_text = canonical_md_text

    actual_json_hash = _sha256_text(final_json_text)
    actual_md_hash = _sha256_text(final_md_text)

    actual_sums_hashes = {
        "calibration_registry_snapshot_diff.json": actual_json_hash,
        "calibration_registry_snapshot_diff.md": actual_md_hash,
    }
    actual_sha256sums = _render_sha256sums(actual_sums_hashes)
    actual_sums_hash = _sha256_text(actual_sha256sums)

    file_contents = {
        "calibration_registry_snapshot_diff.json": final_json_text,
        "calibration_registry_snapshot_diff.md": final_md_text,
        "SHA256SUMS.txt": actual_sha256sums,
    }
    for file_name, content in file_contents.items():
        (output_dir / file_name).write_text(content, encoding="utf-8", newline="\n")

    result = {
        "status": "compared",
        "reasons": diff_result["reasons"],
        "output_dir": str(output_dir),
        "before_snapshot_dir": str(before_dir),
        "after_snapshot_dir": str(after_dir),
        "before_snapshot_hash": diff_result["before_snapshot_hash"],
        "after_snapshot_hash": diff_result["after_snapshot_hash"],
        "before_artifact_count": diff_result["before_artifact_count"],
        "after_artifact_count": diff_result["after_artifact_count"],
        "added_count": diff_result["added_count"],
        "removed_count": diff_result["removed_count"],
        "changed_count": diff_result["changed_count"],
        "unchanged_count": diff_result["unchanged_count"],
        "diff_hash": diff_result["diff_hash"],
        "files": evidence_files,
        "file_hashes": {
            "calibration_registry_snapshot_diff.json": actual_json_hash,
            "calibration_registry_snapshot_diff.md": actual_md_hash,
            "SHA256SUMS.txt": actual_sums_hash,
        },
    }
    if args.output == "markdown":
        print(_render_calibration_label_registry_snapshot_diff_export_stdout_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0


def _render_calibration_label_registry_snapshot_diff_export_verify_markdown(result: dict) -> str:
    lines = [
        "# Calibration Registry Snapshot Diff Export Verification",
        "",
        f"- Status: `{result['status']}`",
        f"- Diff hash: `{result.get('diff_hash', '')}`",
        f"- Before snapshot hash: `{result.get('before_snapshot_hash', '')}`",
        f"- After snapshot hash: `{result.get('after_snapshot_hash', '')}`",
        f"- Added: `{result.get('added_count', 0)}`",
        f"- Removed: `{result.get('removed_count', 0)}`",
        f"- Changed: `{result.get('changed_count', 0)}`",
        f"- Unchanged: `{result.get('unchanged_count', 0)}`",
        "",
        "## Files",
        "",
    ]
    for file_name in result.get("files", []):
        lines.append(f"- `{file_name}`")
    lines.extend(["", "## Reasons", ""])
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _verify_diff_export_evidence(evidence_dir: Path) -> dict:
    files = [
        "calibration_registry_snapshot_diff.json",
        "calibration_registry_snapshot_diff.md",
        "SHA256SUMS.txt",
    ]
    reasons: list[str] = []
    file_hashes: dict[str, str] = {}
    texts: dict[str, str] = {}

    for file_name in files:
        path = evidence_dir / file_name
        if not path.exists():
            reasons.append(f"Missing required evidence file: {file_name}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            reasons.append(f"Evidence file is not valid UTF-8 text: {file_name}")
            continue
        texts[file_name] = text
        file_hashes[file_name] = _sha256_text(text)

    sha256sums_valid = True
    sha256_entries: dict[str, str] = {}
    if "SHA256SUMS.txt" in texts:
        for raw_line in texts["SHA256SUMS.txt"].splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.fullmatch(r"([0-9a-f]{64})\s{2}(.+)", line)
            if match is None:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt contains malformed line: {raw_line}")
                continue
            sha256_entries[match.group(2)] = match.group(1)

        required_checksum_files = {
            "calibration_registry_snapshot_diff.json",
            "calibration_registry_snapshot_diff.md",
        }
        for file_name in sorted(required_checksum_files.difference(sha256_entries)):
            sha256sums_valid = False
            reasons.append(f"SHA256SUMS.txt missing hash entry for {file_name}")
        if "SHA256SUMS.txt" in sha256_entries:
            sha256sums_valid = False
            reasons.append("SHA256SUMS.txt must not contain a self-hash line")
        for file_name in sorted(required_checksum_files.intersection(file_hashes)):
            if sha256_entries.get(file_name) != file_hashes[file_name]:
                sha256sums_valid = False
                reasons.append(f"SHA256SUMS.txt hash mismatch for {file_name}")
    else:
        sha256sums_valid = False

    evidence_json = None
    json_valid = True
    if "calibration_registry_snapshot_diff.json" in texts:
        try:
            evidence_json = json.loads(texts["calibration_registry_snapshot_diff.json"])
            if not isinstance(evidence_json, dict):
                reasons.append("Evidence JSON must contain a JSON object")
                evidence_json = None
                json_valid = False
        except json.JSONDecodeError:
            reasons.append("Evidence file is not valid JSON: calibration_registry_snapshot_diff.json")
            json_valid = False

    markdown_valid = True
    md_text = texts.get("calibration_registry_snapshot_diff.md", "")
    if md_text:
        required_md_sections = [
            "# Calibration Registry Snapshot Diff",
            "Diff hash:",
            "Before snapshot hash:",
            "After snapshot hash:",
            "Added:",
            "Removed:",
            "Changed:",
            "Unchanged:",
            "## Files",
            "## Reasons",
            "## Added Artifacts",
            "## Removed Artifacts",
            "## Changed Artifacts",
            "## Unchanged Artifacts",
        ]
        for section in required_md_sections:
            if section not in md_text:
                markdown_valid = False
                reasons.append(f"Evidence markdown missing required section: {section}")

    diff_hash_valid = True
    evidence_cross_checks_valid = True
    diff_hash = None
    before_snapshot_hash = None
    after_snapshot_hash = None
    added_count = 0
    removed_count = 0
    changed_count = 0
    unchanged_count = 0

    if evidence_json is not None:
        if evidence_json.get("snapshot_diff_type") != "calibration_registry_snapshot_diff":
            json_valid = False
            reasons.append("JSON snapshot_diff_type must be calibration_registry_snapshot_diff")
        if evidence_json.get("snapshot_diff_version") != 1:
            json_valid = False
            reasons.append("JSON snapshot_diff_version must be 1")
        if evidence_json.get("status") != "compared":
            json_valid = False
            reasons.append("JSON status must be compared")
        if evidence_json.get("before_valid") is not True:
            json_valid = False
            reasons.append("JSON before_valid must be true")
        if evidence_json.get("after_valid") is not True:
            json_valid = False
            reasons.append("JSON after_valid must be true")

        diff_hash = evidence_json.get("diff_hash")
        before_snapshot_hash = evidence_json.get("before_snapshot_hash")
        after_snapshot_hash = evidence_json.get("after_snapshot_hash")

        # Required count fields must exist and be integers
        count_fields = {
            "added_count": "JSON added_count must be an integer",
            "removed_count": "JSON removed_count must be an integer",
            "changed_count": "JSON changed_count must be an integer",
            "unchanged_count": "JSON unchanged_count must be an integer",
        }
        for field, msg in count_fields.items():
            if field not in evidence_json:
                json_valid = False
                reasons.append(f"JSON missing required field: {field}")
            elif not isinstance(evidence_json[field], int):
                json_valid = False
                reasons.append(msg)

        added_count = evidence_json.get("added_count", 0)
        removed_count = evidence_json.get("removed_count", 0)
        changed_count = evidence_json.get("changed_count", 0)
        unchanged_count = evidence_json.get("unchanged_count", 0)

        # Required row arrays must exist and be lists
        row_fields = {
            "added": "JSON added must be a list",
            "removed": "JSON removed must be a list",
            "changed": "JSON changed must be a list",
            "unchanged": "JSON unchanged must be a list",
        }
        for field, msg in row_fields.items():
            if field not in evidence_json:
                json_valid = False
                reasons.append(f"JSON missing required field: {field}")

        actual_added = evidence_json.get("added")
        actual_removed = evidence_json.get("removed")
        actual_changed = evidence_json.get("changed")
        actual_unchanged = evidence_json.get("unchanged")

        if actual_added is not None and not isinstance(actual_added, list):
            json_valid = False
            reasons.append("JSON added must be a list")
        if actual_removed is not None and not isinstance(actual_removed, list):
            json_valid = False
            reasons.append("JSON removed must be a list")
        if actual_changed is not None and not isinstance(actual_changed, list):
            json_valid = False
            reasons.append("JSON changed must be a list")
        if actual_unchanged is not None and not isinstance(actual_unchanged, list):
            json_valid = False
            reasons.append("JSON unchanged must be a list")

        actual_added = actual_added if isinstance(actual_added, list) else []
        actual_removed = actual_removed if isinstance(actual_removed, list) else []
        actual_changed = actual_changed if isinstance(actual_changed, list) else []
        actual_unchanged = actual_unchanged if isinstance(actual_unchanged, list) else []

        if len(actual_added) != added_count:
            evidence_cross_checks_valid = False
            reasons.append(f"JSON added length ({len(actual_added)}) does not match added_count ({added_count})")
        if len(actual_removed) != removed_count:
            evidence_cross_checks_valid = False
            reasons.append(f"JSON removed length ({len(actual_removed)}) does not match removed_count ({removed_count})")
        if len(actual_changed) != changed_count:
            evidence_cross_checks_valid = False
            reasons.append(f"JSON changed length ({len(actual_changed)}) does not match changed_count ({changed_count})")
        if len(actual_unchanged) != unchanged_count:
            evidence_cross_checks_valid = False
            reasons.append(f"JSON unchanged length ({len(actual_unchanged)}) does not match unchanged_count ({unchanged_count})")

        # Changed rows validation
        for i, row in enumerate(actual_changed):
            if not isinstance(row, dict):
                evidence_cross_checks_valid = False
                reasons.append(f"Changed row {i} must be a JSON object")
                continue
            for required_key in ("artifact_hash", "before", "after", "changed_fields"):
                if required_key not in row:
                    evidence_cross_checks_valid = False
                    reasons.append(f"Changed row {i} missing required field: {required_key}")
            changed_fields = row.get("changed_fields")
            if changed_fields is not None and not isinstance(changed_fields, list):
                evidence_cross_checks_valid = False
                reasons.append(f"Changed row {i} changed_fields must be a list")
            elif isinstance(changed_fields, list) and changed_fields != sorted(changed_fields):
                evidence_cross_checks_valid = False
                reasons.append(f"Changed row {i} changed_fields are not sorted alphabetically")

        # diff_hash validation using Phase 22 canonical rules
        if not diff_hash:
            diff_hash_valid = False
            reasons.append("diff_hash must be a non-empty string")
        elif not isinstance(diff_hash, str):
            diff_hash_valid = False
            reasons.append("diff_hash must be a string")
        elif (
            json_valid
            and evidence_cross_checks_valid
            and isinstance(actual_added, list)
            and isinstance(actual_removed, list)
            and isinstance(actual_changed, list)
            and isinstance(actual_unchanged, list)
        ):
            expected_hash = _compute_diff_hash(
                before_snapshot_hash=before_snapshot_hash,
                after_snapshot_hash=after_snapshot_hash,
                added=actual_added,
                removed=actual_removed,
                changed=actual_changed,
                unchanged=actual_unchanged,
            )
            if diff_hash != expected_hash:
                diff_hash_valid = False
                reasons.append("diff_hash does not match canonical hash of evidence contents")

        # markdown diff_hash consistency
        if md_text and diff_hash:
            md_hash_match = re.search(r"Diff hash:\s*`([^`]+)`", md_text)
            if md_hash_match is None:
                markdown_valid = False
                reasons.append("Evidence markdown missing diff_hash line")
            elif md_hash_match.group(1) != diff_hash:
                markdown_valid = False
                reasons.append("Evidence markdown diff_hash does not match JSON diff_hash")

        # Safety checks: no full label payload or coordinate fields
        forbidden_label_fields = {"labels", "label_ids"}
        forbidden_coordinate_fields = {
            "lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox"
        }
        json_str = texts.get("calibration_registry_snapshot_diff.json", "")
        for field in forbidden_label_fields:
            if f'"{field}"' in json_str:
                evidence_cross_checks_valid = False
                reasons.append(f"Evidence JSON contains forbidden label payload field: {field}")
        for field in forbidden_coordinate_fields:
            if f'"{field}"' in json_str:
                evidence_cross_checks_valid = False
                reasons.append(f"Evidence JSON contains forbidden coordinate field: {field}")

        if md_text:
            for field in forbidden_label_fields:
                if field in md_text:
                    evidence_cross_checks_valid = False
                    reasons.append(f"Evidence markdown contains forbidden label payload field: {field}")
            for field in forbidden_coordinate_fields:
                if field in md_text:
                    evidence_cross_checks_valid = False
                    reasons.append(f"Evidence markdown contains forbidden coordinate field: {field}")

    status = (
        "valid"
        if (
            sha256sums_valid
            and json_valid
            and markdown_valid
            and diff_hash_valid
            and evidence_cross_checks_valid
            and evidence_json is not None
            and "calibration_registry_snapshot_diff.md" in texts
            and "SHA256SUMS.txt" in texts
        )
        else "invalid"
    )
    if status == "valid":
        reasons = ["Calibration registry snapshot diff evidence pack is valid"]

    return {
        "status": status,
        "reasons": reasons,
        "evidence_dir": str(evidence_dir),
        "diff_hash": diff_hash,
        "before_snapshot_hash": before_snapshot_hash,
        "after_snapshot_hash": after_snapshot_hash,
        "added_count": added_count,
        "removed_count": removed_count,
        "changed_count": changed_count,
        "unchanged_count": unchanged_count,
        "files": files,
        "file_hashes": file_hashes,
        "sha256sums_valid": sha256sums_valid,
        "json_valid": json_valid,
        "markdown_valid": markdown_valid,
        "diff_hash_valid": diff_hash_valid,
        "evidence_cross_checks_valid": evidence_cross_checks_valid,
    }


def cmd_calibration_label_registry_snapshot_diff_export_verify(args: argparse.Namespace) -> int:
    result = _verify_diff_export_evidence(Path(args.evidence_dir))
    if args.output == "markdown":
        print(_render_calibration_label_registry_snapshot_diff_export_verify_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "valid" else 1


def _render_calibration_label_registry_snapshot_diff_export_accept_markdown(result: dict) -> str:
    lines = [
        "# Calibration Registry Snapshot Diff Acceptance",
        "",
        f"- Status: `{result['status']}`",
        f"- Policy: `{result.get('policy_id', '')}` v{result.get('policy_version', '')}",
        f"- Decision hash: `{result.get('decision_hash', '')}`",
        f"- Diff hash: `{result.get('diff_hash', '')}`",
        f"- Before snapshot hash: `{result.get('before_snapshot_hash', '')}`",
        f"- After snapshot hash: `{result.get('after_snapshot_hash', '')}`",
        f"- Added: `{result.get('added_count', 0)}`",
        f"- Removed: `{result.get('removed_count', 0)}`",
        f"- Changed: `{result.get('changed_count', 0)}`",
        f"- Unchanged: `{result.get('unchanged_count', 0)}`",
        "",
        "## Files",
        "",
    ]
    for f in result.get("files", []):
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## Reasons",
        "",
    ])
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _compute_decision_hash(
    policy_id: str,
    policy_version: int,
    diff_hash: str | None,
    before_snapshot_hash: str | None,
    after_snapshot_hash: str | None,
    added_count: int,
    removed_count: int,
    changed_count: int,
    unchanged_count: int,
    status: str,
    reasons: list[str],
) -> str:
    return _stable_hash(
        {
            "policy_id": policy_id,
            "policy_version": policy_version,
            "diff_hash": diff_hash,
            "before_snapshot_hash": before_snapshot_hash,
            "after_snapshot_hash": after_snapshot_hash,
            "added_count": added_count,
            "removed_count": removed_count,
            "changed_count": changed_count,
            "unchanged_count": unchanged_count,
            "status": status,
            "reasons": reasons,
        }
    )


def _accept_diff_export_evidence(evidence_dir: Path) -> dict:
    policy_id = "calibration_registry_diff_acceptance_v1"
    policy_version = 1

    verify_result = _verify_diff_export_evidence(evidence_dir)

    reasons: list[str] = []
    evidence_valid = verify_result["status"] == "valid"

    if not evidence_valid:
        reasons.append("Evidence pack verification failed")
        reasons.extend(verify_result["reasons"])

    added_count = verify_result.get("added_count", 0)
    removed_count = verify_result.get("removed_count", 0)
    changed_count = verify_result.get("changed_count", 0)
    unchanged_count = verify_result.get("unchanged_count", 0)

    if evidence_valid:
        if removed_count > 0:
            reasons.append(f"Policy rejects evidence with removed_count={removed_count} (must be 0)")
        if changed_count > 0:
            reasons.append(f"Policy rejects evidence with changed_count={changed_count} (must be 0)")
        if added_count < 0:
            reasons.append(f"Policy rejects evidence with added_count={added_count} (must be >= 0)")

    if evidence_valid and removed_count == 0 and changed_count == 0 and added_count >= 0:
        status = "accepted"
        reasons = ["Evidence pack passes calibration registry diff acceptance policy"]
    elif not evidence_valid:
        status = "invalid"
    else:
        status = "rejected"

    decision_hash = _compute_decision_hash(
        policy_id=policy_id,
        policy_version=policy_version,
        diff_hash=verify_result.get("diff_hash"),
        before_snapshot_hash=verify_result.get("before_snapshot_hash"),
        after_snapshot_hash=verify_result.get("after_snapshot_hash"),
        added_count=added_count,
        removed_count=removed_count,
        changed_count=changed_count,
        unchanged_count=unchanged_count,
        status=status,
        reasons=reasons,
    )

    return {
        "status": status,
        "reasons": reasons,
        "evidence_dir": str(evidence_dir),
        "policy_id": policy_id,
        "policy_version": policy_version,
        "diff_hash": verify_result.get("diff_hash"),
        "before_snapshot_hash": verify_result.get("before_snapshot_hash"),
        "after_snapshot_hash": verify_result.get("after_snapshot_hash"),
        "added_count": added_count,
        "removed_count": removed_count,
        "changed_count": changed_count,
        "unchanged_count": unchanged_count,
        "evidence_valid": evidence_valid,
        "sha256sums_valid": verify_result.get("sha256sums_valid", False),
        "json_valid": verify_result.get("json_valid", False),
        "markdown_valid": verify_result.get("markdown_valid", False),
        "diff_hash_valid": verify_result.get("diff_hash_valid", False),
        "evidence_cross_checks_valid": verify_result.get("evidence_cross_checks_valid", False),
        "decision_hash": decision_hash,
        "files": verify_result.get("files", []),
        "file_hashes": verify_result.get("file_hashes", {}),
    }


def cmd_calibration_label_registry_snapshot_diff_export_accept(args: argparse.Namespace) -> int:
    result = _accept_diff_export_evidence(Path(args.evidence_dir))
    if args.output == "markdown":
        print(_render_calibration_label_registry_snapshot_diff_export_accept_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))
    return 0 if result["status"] == "accepted" else 1


def _compute_signoff_hash(
    signoff_evidence_type: str,
    signoff_evidence_version: int,
    status: str,
    reasons: list[str],
    policy_id: str,
    policy_version: int,
    acceptance_status: str,
    decision_hash: str | None,
    diff_hash: str | None,
    before_snapshot_hash: str | None,
    after_snapshot_hash: str | None,
    added_count: int,
    removed_count: int,
    changed_count: int,
    unchanged_count: int,
) -> str:
    return _stable_hash(
        {
            "signoff_evidence_type": signoff_evidence_type,
            "signoff_evidence_version": signoff_evidence_version,
            "status": status,
            "reasons": reasons,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "acceptance_status": acceptance_status,
            "decision_hash": decision_hash,
            "diff_hash": diff_hash,
            "before_snapshot_hash": before_snapshot_hash,
            "after_snapshot_hash": after_snapshot_hash,
            "added_count": added_count,
            "removed_count": removed_count,
            "changed_count": changed_count,
            "unchanged_count": unchanged_count,
        }
    )


def _render_calibration_signoff_evidence_markdown(result: dict) -> str:
    lines = [
        "# Calibration Sign-off Evidence",
        "",
        f"- Status: `{result['status']}`",
        f"- Acceptance status: `{result.get('acceptance_status', '')}`",
        f"- Policy: `{result.get('policy_id', '')}` v{result.get('policy_version', '')}",
        f"- Decision hash: `{result.get('decision_hash', '')}`",
        f"- Sign-off hash: `{result.get('signoff_hash', '')}`",
        f"- Diff hash: `{result.get('diff_hash', '')}`",
        f"- Before snapshot hash: `{result.get('before_snapshot_hash', '')}`",
        f"- After snapshot hash: `{result.get('after_snapshot_hash', '')}`",
        f"- Added: `{result.get('added_count', 0)}`",
        f"- Removed: `{result.get('removed_count', 0)}`",
        f"- Changed: `{result.get('changed_count', 0)}`",
        f"- Unchanged: `{result.get('unchanged_count', 0)}`",
        "",
        "## Files",
        "",
    ]
    for f in result.get("files", []):
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## Reasons",
        "",
    ])
    lines.extend(f"- {reason}" for reason in result["reasons"])
    return "\n".join(lines) + "\n"


def _export_signoff_evidence(evidence_dir: Path, output_dir: Path) -> dict:
    acceptance = _accept_diff_export_evidence(evidence_dir)
    acceptance_status = acceptance["status"]

    if acceptance_status == "accepted":
        status = "ready"
        reasons = ["Calibration sign-off evidence is ready"]
    elif acceptance_status == "rejected":
        status = "rejected"
        reasons = acceptance["reasons"]
    else:
        status = "invalid"
        reasons = acceptance["reasons"]

    signoff_evidence_type = "calibration_signoff_evidence"
    signoff_evidence_version = 1

    signoff_hash = _compute_signoff_hash(
        signoff_evidence_type=signoff_evidence_type,
        signoff_evidence_version=signoff_evidence_version,
        status=status,
        reasons=reasons,
        policy_id=acceptance.get("policy_id", ""),
        policy_version=acceptance.get("policy_version", 1),
        acceptance_status=acceptance_status,
        decision_hash=acceptance.get("decision_hash"),
        diff_hash=acceptance.get("diff_hash"),
        before_snapshot_hash=acceptance.get("before_snapshot_hash"),
        after_snapshot_hash=acceptance.get("after_snapshot_hash"),
        added_count=acceptance.get("added_count", 0),
        removed_count=acceptance.get("removed_count", 0),
        changed_count=acceptance.get("changed_count", 0),
        unchanged_count=acceptance.get("unchanged_count", 0),
    )

    return {
        "signoff_evidence_type": signoff_evidence_type,
        "signoff_evidence_version": signoff_evidence_version,
        "status": status,
        "reasons": reasons,
        "evidence_dir": str(evidence_dir),
        "source_evidence_dir": str(evidence_dir),
        "policy_id": acceptance.get("policy_id", ""),
        "policy_version": acceptance.get("policy_version", 1),
        "acceptance_status": acceptance_status,
        "acceptance_result": acceptance,
        "decision_hash": acceptance.get("decision_hash"),
        "diff_hash": acceptance.get("diff_hash"),
        "before_snapshot_hash": acceptance.get("before_snapshot_hash"),
        "after_snapshot_hash": acceptance.get("after_snapshot_hash"),
        "added_count": acceptance.get("added_count", 0),
        "removed_count": acceptance.get("removed_count", 0),
        "changed_count": acceptance.get("changed_count", 0),
        "unchanged_count": acceptance.get("unchanged_count", 0),
        "evidence_valid": acceptance.get("evidence_valid", False),
        "sha256sums_valid": acceptance.get("sha256sums_valid", False),
        "json_valid": acceptance.get("json_valid", False),
        "markdown_valid": acceptance.get("markdown_valid", False),
        "diff_hash_valid": acceptance.get("diff_hash_valid", False),
        "evidence_cross_checks_valid": acceptance.get("evidence_cross_checks_valid", False),
        "files": [
            "calibration_signoff_evidence.json",
            "calibration_signoff_evidence.md",
            "SHA256SUMS.txt",
        ],
        "source_evidence_file_hashes": acceptance.get("file_hashes", {}),
        "bundle_file_manifest_policy": "Bundle file content hashes are recorded in SHA256SUMS.txt to avoid self-referential JSON hashing.",
        "signoff_hash": signoff_hash,
    }


def cmd_calibration_signoff_evidence_export(args: argparse.Namespace) -> int:
    evidence_dir = Path(args.evidence_dir)
    output_dir = Path(args.output_dir)

    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        result = {
            "status": "invalid",
            "reasons": ["Output directory exists and is not empty. Use --overwrite to replace."],
            "evidence_dir": str(evidence_dir),
            "source_evidence_dir": str(evidence_dir),
            "output_dir": str(output_dir),
        }
        if args.output == "markdown":
            print(_render_calibration_signoff_evidence_markdown(result), end="")
        else:
            print(json.dumps(result, indent=2))
        return 1

    result = _export_signoff_evidence(evidence_dir, output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "calibration_signoff_evidence.json"
    md_path = output_dir / "calibration_signoff_evidence.md"
    sums_path = output_dir / "SHA256SUMS.txt"

    json_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    md_text = _render_calibration_signoff_evidence_markdown(result)

    json_path.write_text(json_text, encoding="utf-8", newline="\n")
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    json_hash = _sha256_text(json_text)
    md_hash = _sha256_text(md_text)
    sums_text = f"{json_hash}  calibration_signoff_evidence.json\n{md_hash}  calibration_signoff_evidence.md\n"
    sums_path.write_text(sums_text, encoding="utf-8", newline="\n")

    if args.output == "markdown":
        print(_render_calibration_signoff_evidence_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2))

    return 0 if result["status"] == "ready" else 1


def cmd_reproducibility_check(args: argparse.Namespace) -> int:
    repository = AcceptanceRepository(load_settings().db_path)
    baseline_run = repository.fetch_run(args.run_id)
    comparison_run = repository.fetch_run(args.comparison_run_id)
    if baseline_run is None:
        print(f"run not found: {args.run_id}", file=sys.stderr)
        return 1
    if comparison_run is None:
        print(f"run not found: {args.comparison_run_id}", file=sys.stderr)
        return 1
    result = reproducibility_check(
        baseline_run=baseline_run,
        comparison_run=comparison_run,
        baseline_candidates=repository.fetch_candidate_rows(args.run_id),
        comparison_candidates=repository.fetch_candidate_rows(args.comparison_run_id),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"pass", "warn"} else 1


def _add_legal_gate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--attestation",
        default="missing",
    )
    parser.add_argument(
        "--geofence",
        default="missing",
    )


def _add_create_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--source-endpoint-id", default=None)
    parser.add_argument("--aoi-path", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)


def _add_review_queue_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)


def _add_scaffold_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)


def _add_execute_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)


def _add_run_summary_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)


def _add_review_show_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", required=True)


def _add_review_decide_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument(
        "--decision",
        required=True,
        choices=["reject", "watch", "approve_for_archive_quote"],
    )
    parser.add_argument("--note", default=None)


def _add_paid_quote_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--provider-quote-id", required=True)
    parser.add_argument("--amount", required=True, type=float)
    parser.add_argument("--credits", required=True, type=float)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--eula-reference", required=True)
    parser.add_argument("--project-id", default=None)


def _add_paid_quote_show_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--provider-quote-id", default=None)


def _add_paid_order_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--provider-quote-id", required=True)
    parser.add_argument("--provider-order-id", required=True)
    parser.add_argument("--requested-by", required=True)


def _add_paid_order_show_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--candidate-id", default=None)
    parser.add_argument("--provider-order-id", default=None)


def _add_paid_order_status_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider-order-id", required=True)
    parser.add_argument(
        "--paid-status",
        required=True,
        choices=[ORDER_STATUS_CONFIRMED, ORDER_STATUS_DELIVERED, ORDER_STATUS_CANCELLED],
    )


def _add_export_bundle_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bundle-manifest-path", required=True)
    parser.add_argument("--export-root", default=".")
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_export_bundle_verify_batch_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--manifest-list", default=None)
    parser.add_argument("--export-root", default=".")
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--fail-fast", action="store_true")


def _add_release_evidence_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_release_evidence_index_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--evidence-list", default=None)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--fail-fast", action="store_true")


def _add_export_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--requested-precision", default=None)


def _add_kpi_summary_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--aoi-area-km2", required=True, type=float)
    parser.add_argument("--time-to-first-review-package-hours", type=float, default=None)


def _add_acceptance_check_arguments(parser: argparse.ArgumentParser) -> None:
    _add_kpi_summary_arguments(parser)
    parser.add_argument("--retuned-run-id", default=None)
    parser.add_argument("--comparison-run-id", default=None)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_reproducibility_check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comparison-run-id", required=True)


def _add_calibration_pack_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comparison-run-id", default=None)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_pack_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--include-pending", action="store_true")


def _add_calibration_label_manifest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--include-pending", action="store_true")


def _add_calibration_label_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--include-pending", action="store_true")


def _add_calibration_label_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_register_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_list_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_snapshot_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_snapshot_diff_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--before-snapshot-dir", required=True)
    parser.add_argument("--after-snapshot-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_snapshot_diff_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--before-snapshot-dir", required=True)
    parser.add_argument("--after-snapshot-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--overwrite", action="store_true")


def _add_calibration_label_registry_snapshot_diff_export_verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_label_registry_snapshot_diff_export_accept_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_calibration_signoff_evidence_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output", choices=["json", "markdown"], default="json")
    parser.add_argument("--overwrite", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lawful-anomaly-screening")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "version": cmd_version,
        "show-config": cmd_show_config,
        "show-baseline": cmd_show_baseline,
        "init-db": cmd_init_db,
        "validate-aoi": cmd_validate_aoi,
        "legal-check": cmd_legal_check,
        "create-run": cmd_create_run,
        "scaffold-run": cmd_scaffold_run,
        "execute-run": cmd_execute_run,
        "review-queue": cmd_review_queue,
        "review-show": cmd_review_show,
        "review-decide": cmd_review_decide,
        "export-bundle-verify": cmd_export_bundle_verify,
        "export-bundle-verify-batch": cmd_export_bundle_verify_batch,
        "release-evidence-verify": cmd_release_evidence_verify,
        "release-evidence-index-verify": cmd_release_evidence_index_verify,
        "export-create": cmd_export_create,
        "run-summary": cmd_run_summary,
        "paid-quote-create": cmd_paid_quote_create,
        "paid-quote-show": cmd_paid_quote_show,
        "paid-order-create": cmd_paid_order_create,
        "paid-order-show": cmd_paid_order_show,
        "paid-order-status": cmd_paid_order_status,
        "kpi-summary": cmd_kpi_summary,
        "acceptance-check": cmd_acceptance_check,
        "calibration-pack": cmd_calibration_pack,
        "calibration-label-pack": cmd_calibration_label_pack,
        "calibration-label-manifest": cmd_calibration_label_manifest,
        "calibration-label-export": cmd_calibration_label_export,
        "calibration-label-verify": cmd_calibration_label_verify,
        "calibration-label-register": cmd_calibration_label_register,
        "calibration-label-registry-list": cmd_calibration_label_registry_list,
        "calibration-label-registry-export": cmd_calibration_label_registry_export,
        "calibration-label-registry-snapshot-verify": cmd_calibration_label_registry_snapshot_verify,
        "calibration-label-registry-snapshot-diff": cmd_calibration_label_registry_snapshot_diff,
        "calibration-label-registry-snapshot-diff-export": cmd_calibration_label_registry_snapshot_diff_export,
        "calibration-label-registry-snapshot-diff-export-verify": cmd_calibration_label_registry_snapshot_diff_export_verify,
        "calibration-label-registry-snapshot-diff-export-accept": cmd_calibration_label_registry_snapshot_diff_export_accept,
        "calibration-signoff-evidence-export": cmd_calibration_signoff_evidence_export,
        "reproducibility-check": cmd_reproducibility_check,
    }
    for name, func in commands.items():
        p = sub.add_parser(name)
        if name in {"legal-check", "create-run"}:
            _add_legal_gate_arguments(p)
        if name == "create-run":
            _add_create_run_arguments(p)
        if name == "review-queue":
            _add_review_queue_arguments(p)
        if name == "scaffold-run":
            _add_scaffold_run_arguments(p)
        if name == "execute-run":
            _add_execute_run_arguments(p)
        if name == "review-show":
            _add_review_show_arguments(p)
        if name == "review-decide":
            _add_review_decide_arguments(p)
        if name == "export-bundle-verify":
            _add_export_bundle_verify_arguments(p)
        if name == "export-bundle-verify-batch":
            _add_export_bundle_verify_batch_arguments(p)
        if name == "release-evidence-verify":
            _add_release_evidence_verify_arguments(p)
        if name == "release-evidence-index-verify":
            _add_release_evidence_index_verify_arguments(p)
        if name == "export-create":
            _add_export_create_arguments(p)
        if name == "run-summary":
            _add_run_summary_arguments(p)
        if name == "paid-quote-create":
            _add_paid_quote_create_arguments(p)
        if name == "paid-quote-show":
            _add_paid_quote_show_arguments(p)
        if name == "paid-order-create":
            _add_paid_order_create_arguments(p)
        if name == "paid-order-show":
            _add_paid_order_show_arguments(p)
        if name == "paid-order-status":
            _add_paid_order_status_arguments(p)
        if name == "kpi-summary":
            _add_kpi_summary_arguments(p)
        if name == "acceptance-check":
            _add_acceptance_check_arguments(p)
        if name == "calibration-pack":
            _add_calibration_pack_arguments(p)
        if name == "calibration-label-pack":
            _add_calibration_label_pack_arguments(p)
        if name == "calibration-label-manifest":
            _add_calibration_label_manifest_arguments(p)
        if name == "calibration-label-export":
            _add_calibration_label_export_arguments(p)
        if name == "calibration-label-verify":
            _add_calibration_label_verify_arguments(p)
        if name == "calibration-label-register":
            _add_calibration_label_register_arguments(p)
        if name == "calibration-label-registry-list":
            _add_calibration_label_registry_list_arguments(p)
        if name == "calibration-label-registry-export":
            _add_calibration_label_registry_export_arguments(p)
        if name == "calibration-label-registry-snapshot-verify":
            _add_calibration_label_registry_snapshot_verify_arguments(p)
        if name == "calibration-label-registry-snapshot-diff":
            _add_calibration_label_registry_snapshot_diff_arguments(p)
        if name == "calibration-label-registry-snapshot-diff-export":
            _add_calibration_label_registry_snapshot_diff_export_arguments(p)
        if name == "calibration-label-registry-snapshot-diff-export-verify":
            _add_calibration_label_registry_snapshot_diff_export_verify_arguments(p)
        if name == "calibration-label-registry-snapshot-diff-export-accept":
            _add_calibration_label_registry_snapshot_diff_export_accept_arguments(p)
        if name == "calibration-signoff-evidence-export":
            _add_calibration_signoff_evidence_export_arguments(p)
        if name == "reproducibility-check":
            _add_reproducibility_check_arguments(p)
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        ExportPolicyError,
        LegalGateError,
        PaidFlowError,
        ReviewDecisionError,
        ReviewStateError,
        SourceError,
        ValueError,
    ) as exc:
        prefix = "Error"
        if isinstance(exc, SourceError):
            prefix = "Source Error"
        print(f"{prefix}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
