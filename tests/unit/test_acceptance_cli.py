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
    label_pack_args = parser.parse_args(
        [
            "calibration-label-pack",
            "--run-id",
            "run-001",
            "--output",
            "markdown",
            "--include-pending",
        ]
    )
    label_manifest_args = parser.parse_args(
        [
            "calibration-label-manifest",
            "--run-id",
            "run-001",
            "--output",
            "markdown",
            "--include-pending",
        ]
    )
    label_export_args = parser.parse_args(
        [
            "calibration-label-export",
            "--run-id",
            "run-001",
            "--output-dir",
            "artifacts",
            "--include-pending",
        ]
    )
    label_verify_args = parser.parse_args(
        [
            "calibration-label-verify",
            "--artifact-dir",
            "artifacts",
            "--output",
            "markdown",
        ]
    )
    label_register_args = parser.parse_args(
        [
            "calibration-label-register",
            "--artifact-dir",
            "artifacts",
            "--output",
            "markdown",
        ]
    )
    label_registry_list_args = parser.parse_args(
        [
            "calibration-label-registry-list",
            "--output",
            "markdown",
        ]
    )
    label_registry_export_args = parser.parse_args(
        [
            "calibration-label-registry-export",
            "--output-dir",
            "registry_snapshot",
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
    assert label_pack_args.command == "calibration-label-pack"
    assert label_pack_args.output == "markdown"
    assert label_pack_args.include_pending is True
    assert label_manifest_args.command == "calibration-label-manifest"
    assert label_manifest_args.output == "markdown"
    assert label_manifest_args.include_pending is True
    assert label_export_args.command == "calibration-label-export"
    assert label_export_args.output_dir == "artifacts"
    assert label_export_args.include_pending is True
    assert label_verify_args.command == "calibration-label-verify"
    assert label_verify_args.artifact_dir == "artifacts"
    assert label_verify_args.output == "markdown"
    assert label_register_args.command == "calibration-label-register"
    assert label_register_args.artifact_dir == "artifacts"
    assert label_register_args.output == "markdown"
    assert label_registry_list_args.command == "calibration-label-registry-list"
    assert label_registry_list_args.output == "markdown"
    assert label_registry_export_args.command == "calibration-label-registry-export"
    assert label_registry_export_args.output_dir == "registry_snapshot"
    assert label_registry_export_args.output == "markdown"
    assert reproducibility_args.command == "reproducibility-check"
    assert reproducibility_args.comparison_run_id == "run-002"
