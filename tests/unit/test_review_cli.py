from lawful_anomaly_screening.cli import build_parser


def test_review_cli_commands_are_registered():
    parser = build_parser()

    queue_args = parser.parse_args(["review-queue", "--limit", "5"])
    show_args = parser.parse_args(["review-show", "--candidate-id", "candidate-001"])
    decide_args = parser.parse_args(
        [
            "review-decide",
            "--candidate-id",
            "candidate-001",
            "--run-id",
            "run-001",
            "--reviewer-id",
            "reviewer-001",
            "--decision",
            "watch",
            "--note",
            "monitor",
        ]
    )

    assert queue_args.command == "review-queue"
    assert queue_args.limit == 5
    assert show_args.command == "review-show"
    assert show_args.candidate_id == "candidate-001"
    assert decide_args.command == "review-decide"
    assert decide_args.decision == "watch"
