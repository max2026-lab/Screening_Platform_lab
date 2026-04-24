from lawful_anomaly_screening.cli import main


def test_legal_check_defaults_to_manual_review():
    assert main(["legal-check"]) == 1


def test_create_run_fails_when_legal_gate_unresolved():
    # Still fails (main returns 1) because of legal gate, 
    # but we must provide required args to even get to the legal gate check
    assert main([
        "create-run", 
        "--aoi-path", "tests/fixtures/sample_aoi.geojson",
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ]) == 1
