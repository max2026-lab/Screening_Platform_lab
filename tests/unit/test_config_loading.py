import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import load_endpoint_registry
from lawful_anomaly_screening.settings import PACKAGE_ROOT, load_settings


def test_config_loading():
    settings = load_settings()
    assert settings.baseline_path == PACKAGE_ROOT / "config/baselines/baseline_v1_5_default.json"
    assert settings.logging_config_path == PACKAGE_ROOT / "config/logging/logging.yaml"
    assert settings.export_precision_path == PACKAGE_ROOT / "config/exports/precision_tiers.json"
    assert settings.endpoints_path == PACKAGE_ROOT / "config/sources/endpoints.json"
    assert settings.geofence_policy_path == PACKAGE_ROOT / "config/legal/geofence_policy.json"
    assert settings.preprocessing_config_path == PACKAGE_ROOT / "config/sources/preprocessing.json"


def test_endpoint_keys_exist():
    endpoints = json.loads(
        (PACKAGE_ROOT / "config/sources/endpoints.json").read_text(encoding="utf-8")
    )
    assert endpoints["primary"] == "earth_search"
    assert endpoints["fallbacks"] == ["cdse", "landsatlook"]
    assert {"earth_search", "cdse", "landsatlook"} <= set(endpoints)


def test_endpoint_registry_exposes_primary_and_fallbacks():
    registry = load_endpoint_registry()
    assert registry.primary_endpoint.endpoint_id == "earth_search"
    assert [endpoint.endpoint_id for endpoint in registry.fallback_endpoints] == [
        "cdse",
        "landsatlook",
    ]


def test_endpoint_registry_accepts_utf8_bom_json(tmp_path):
    config_path = tmp_path / "endpoints-bom.json"
    config_path.write_text(
        json.dumps(
            {
                "primary": "sim_empty",
                "fallbacks": ["cdse"],
                "sim_empty": {
                    "provider": "simulator-empty",
                    "role": "primary",
                    "synchronous_only": True,
                },
                "cdse": {
                    "provider": "cdse",
                    "role": "fallback",
                    "synchronous_only": True,
                },
            }
        ),
        encoding="utf-8-sig",
    )

    registry = load_endpoint_registry(path=config_path)

    assert registry.primary_endpoint_id == "sim_empty"
    assert registry.primary_endpoint.provider == "simulator-empty"
    assert [endpoint.endpoint_id for endpoint in registry.fallback_endpoints] == ["cdse"]


def test_relative_env_overrides_are_cwd_anchored(monkeypatch):
    monkeypatch.setenv("LAWFUL_ANOMALY_ENDPOINTS_PATH", "my_endpoints.json")
    monkeypatch.setenv("LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH", "my_preprocessing.json")
    monkeypatch.setenv("LAWFUL_ANOMALY_BASELINE_PATH", "my_baseline.json")

    settings = load_settings()

    assert settings.endpoints_path == Path("my_endpoints.json")
    assert settings.preprocessing_config_path == Path("my_preprocessing.json")
    assert settings.baseline_path == Path("my_baseline.json")


def test_baseline_includes_calibration_policy():
    baseline = json.loads(
        (PACKAGE_ROOT / "config/baselines/baseline_v1_5_default.json").read_text(encoding="utf-8")
    )
    policy = baseline["calibration_policy"]
    assert policy["calibration_policy_id"] == "calibration_policy_v1_0_default"
    assert policy["review_coverage_minimum_rate"] == 0.20
    assert policy["top20_review_coverage_minimum_rate"] == 0.50
    assert policy["requires_export_audit_manifest"] is True
    assert policy["requires_reproducibility_comparison"] is True
    assert policy["minimum_candidate_count"] == 1
    assert policy["paid_escalation_required"] is False
