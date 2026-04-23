from lawful_anomaly_screening.orchestration.run_status import RUN_STATUS_BLOCKED


def test_run_status():
    assert RUN_STATUS_BLOCKED == "blocked"
