from lawful_anomaly_screening.cli import build_parser


def test_operator_scaffold_and_export_commands_are_registered():
    parser = build_parser()

    scaffold_args = parser.parse_args(
        [
            "scaffold-run",
            "--run-id",
            "run-001",
        ]
    )
    export_args = parser.parse_args(
        [
            "export-create",
            "--run-id",
            "run-001",
            "--audience",
            "report_pdf",
            "--requested-precision",
            "restricted",
        ]
    )

    assert scaffold_args.command == "scaffold-run"
    assert scaffold_args.run_id == "run-001"
    assert export_args.command == "export-create"
    assert export_args.run_id == "run-001"
    assert export_args.audience == "report_pdf"
    assert export_args.requested_precision == "restricted"
