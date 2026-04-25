from lawful_anomaly_screening.cli import build_parser


def test_acceptance_cli_commands_are_registered():
    parser = build_parser()

    kpi_args = parser.parse_args(
        [
            "kpi-summary",
            "--run-id",
            "run-001",
            "--aoi-area-km2",
            "100",
            "--time-to-first-review-package-hours",
            "1.5",
        ]
    )
    acceptance_args = parser.parse_args(
        [
            "acceptance-check",
            "--run-id",
            "run-001",
            "--aoi-area-km2",
            "100",
            "--retuned-run-id",
            "run-002",
            "--comparison-run-id",
            "run-003",
            "--output",
            "markdown",
        ]
    )
    reproducibility_args = parser.parse_args(
        [
            "reproducibility-check",
            "--run-id",
            "run-001",
            "--comparison-run-id",
            "run-002",
        ]
    )
    calibration_args = parser.parse_args(
        [
            "calibration-pack",
            "--run-id",
            "run-001",
            "--comparison-run-id",
            "run-002",
            "--output",
            "markdown",
        ]
    )

    assert kpi_args.command == "kpi-summary"
    assert kpi_args.aoi_area_km2 == 100.0
    assert kpi_args.time_to_first_review_package_hours == 1.5
    assert acceptance_args.command == "acceptance-check"
    assert acceptance_args.retuned_run_id == "run-002"
    assert acceptance_args.comparison_run_id == "run-003"
    assert acceptance_args.output == "markdown"
    assert calibration_args.command == "calibration-pack"
    assert calibration_args.comparison_run_id == "run-002"
    assert calibration_args.output == "markdown"
    assert reproducibility_args.command == "reproducibility-check"
    assert reproducibility_args.comparison_run_id == "run-002"
