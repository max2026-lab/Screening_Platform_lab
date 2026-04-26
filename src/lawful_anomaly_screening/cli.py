from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from datetime import datetime

from . import __version__
from .aoi.validation import validate_aoi_file
from .db.repositories.acceptance_repository import AcceptanceRepository
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


def cmd_export_create(args: argparse.Namespace) -> int:
    repository = ExportRepository(load_settings().db_path)
    candidates = repository.fetch_export_candidates(args.run_id)
    if not candidates:
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
    artifact_hash = _stable_hash(
        {
            "files": [
                {"name": file_name, "sha256": core_hashes[file_name]}
                for file_name in sorted(core_hashes)
            ],
            "include_pending": bool(args.include_pending),
            "run_id": manifest["run_id"],
        }
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
        "export-create": cmd_export_create,
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
        if name == "export-create":
            _add_export_create_arguments(p)
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
