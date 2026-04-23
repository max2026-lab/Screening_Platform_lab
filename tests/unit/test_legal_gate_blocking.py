from lawful_anomaly_screening.cli import main


def test_legal_check_defaults_to_manual_review():
    assert main(["legal-check"]) == 1


def test_create_run_fails_when_legal_gate_unresolved():
    assert main(["create-run"]) == 1
