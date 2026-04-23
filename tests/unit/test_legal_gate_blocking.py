from lawful_anomaly_screening.cli import main


def test_legal_check():
    assert main(["legal-check"]) == 0
