from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .db.repositories.acceptance_repository import AcceptanceRepository
from .db.repositories.export_repository import ExportRepository
from .db.repositories.manifest_repository import ManifestRepository
from .db.repositories.paid_repository import PaidRepository
from .db.repositories.review_repository import ReviewRepository
from .db.sqlite import bootstrap_minimal_run, init_db
from .exceptions import (
    ExportPolicyError,
    LegalGateError,
    PaidFlowError,
    ReviewDecisionError,
    ReviewStateError,
)
from .orchestration.scaffold_run import scaffold_run_for_run_id
from .legal import LEGAL_OUTCOME_ALLOWED, evaluate_legal_gate
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
    build_kpi_summary,
    render_acceptance_summary_markdown,
    reproducibility_check,
    top10_stability_rate,
)


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_baseline() -> dict:
    return _load_json(load_settings().baseline_path)


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
    print(json.dumps(
        {
            "db_path": str(settings.db_path),
            "baseline_path": str(settings.baseline_path),
            "logging_config_path": str(settings.logging_config_path),
            "export_precision_path": str(settings.export_precision_path),
            "endpoints_path": str(settings.endpoints_path),
            "preprocessing_config_path": str(settings.preprocessing_config_path),
        },
        indent=2,
    ))
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
    outcome = _legal_gate_outcome(_)
    if outcome != LEGAL_OUTCOME_ALLOWED:
        raise LegalGateError(f"legal gate {outcome}")
    settings = load_settings()
    baseline = _load_baseline()
    init_db(settings.db_path)

    registry = load_endpoint_registry()
    source_endpoint_id = _.source_endpoint_id or registry.primary_endpoint_id
    manifest = build_manifest(source_endpoint_id=source_endpoint_id)
    manifest_repository = ManifestRepository(settings.db_path)
    manifest_record = manifest_repository.persist_manifest(manifest)

    run_id = _.run_id or f"run-{manifest_record['source_scene_manifest_hash'][:8]}"
    run_record = bootstrap_minimal_run(
        settings.db_path,
        processing_baseline_id=baseline["processing_baseline_id"],
        score_formula_version=baseline["score_formula_version"],
        source_scene_manifest_hash=manifest_record["source_scene_manifest_hash"],
        source_endpoint_id=manifest_record["source_endpoint_id"],
        run_id=run_id,
        source_name=manifest_record["source_name"],
        manifest_path=manifest_record["manifest_path"],
    )
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
        paid_repository=PaidRepository(db_path),
        review_repository=ReviewRepository(db_path),
        archive_client=Up42ArchiveClient(),
    )


def _build_order_service() -> OrderService:
    db_path = load_settings().db_path
    return OrderService(
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
    kpi_summary = _build_kpi_summary_from_args(args)
    stability_value = None
    if args.retuned_run_id is not None:
        repository = AcceptanceRepository(load_settings().db_path)
        stability_value = top10_stability_rate(
            repository.fetch_candidate_rows(args.run_id),
            repository.fetch_candidate_rows(args.retuned_run_id),
        )
    summary = build_acceptance_summary(
        kpi_summary=kpi_summary,
        top10_stability_rate_value=stability_value,
    )
    if args.output == "markdown":
        print(render_acceptance_summary_markdown(summary), end="")
    else:
        print(json.dumps(summary, indent=2))
    return 0 if summary["status"] in {"pass", "warn"} else 1


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
        baseline_manifest_hash=baseline_run["source_scene_manifest_hash"],
        comparison_manifest_hash=comparison_run["source_scene_manifest_hash"],
        baseline_candidates=repository.fetch_candidate_rows(args.run_id),
        comparison_candidates=repository.fetch_candidate_rows(args.comparison_run_id),
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


def _add_legal_gate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--attestation",
        choices=["present", "missing", "unknown"],
        default="missing",
    )
    parser.add_argument(
        "--geofence",
        choices=["clear", "hit", "missing", "unknown"],
        default="missing",
    )


def _add_create_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--source-endpoint-id", default=None)


def _add_review_queue_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit", type=int, default=None)


def _add_scaffold_run_arguments(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument("--output", choices=["json", "markdown"], default="json")


def _add_reproducibility_check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comparison-run-id", required=True)


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
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
