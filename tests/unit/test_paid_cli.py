from lawful_anomaly_screening.cli import build_parser


def test_paid_cli_commands_are_registered():
    parser = build_parser()

    quote_create_args = parser.parse_args(
        [
            "paid-quote-create",
            "--candidate-id",
            "candidate-001",
            "--provider-quote-id",
            "quote-001",
            "--amount",
            "149.5",
            "--credits",
            "88.0",
            "--currency",
            "usd",
            "--eula-reference",
            "eula-001",
            "--project-id",
            "project-001",
        ]
    )
    quote_show_args = parser.parse_args(
        [
            "paid-quote-show",
            "--provider-quote-id",
            "quote-001",
        ]
    )
    order_create_args = parser.parse_args(
        [
            "paid-order-create",
            "--candidate-id",
            "candidate-001",
            "--provider-quote-id",
            "quote-001",
            "--provider-order-id",
            "order-001",
            "--requested-by",
            "reviewer-001",
        ]
    )
    order_status_args = parser.parse_args(
        [
            "paid-order-status",
            "--provider-order-id",
            "order-001",
            "--paid-status",
            "order_confirmed",
        ]
    )

    assert quote_create_args.command == "paid-quote-create"
    assert quote_create_args.amount == 149.5
    assert quote_create_args.credits == 88.0
    assert quote_show_args.command == "paid-quote-show"
    assert quote_show_args.provider_quote_id == "quote-001"
    assert order_create_args.command == "paid-order-create"
    assert order_create_args.requested_by == "reviewer-001"
    assert order_status_args.command == "paid-order-status"
    assert order_status_args.paid_status == "order_confirmed"
