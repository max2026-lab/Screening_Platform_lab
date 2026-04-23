from lawful_anomaly_screening.settings import load_settings


def test_config_loading():
    assert load_settings().baseline_path.name == "baseline_v1_5_default.json"
