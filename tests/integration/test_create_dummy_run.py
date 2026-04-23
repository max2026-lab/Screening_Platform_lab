from lawful_anomaly_screening.cli import main


def test_create_dummy_run():
    assert main(["create-run", "--attestation", "present", "--geofence", "clear"]) == 0
