import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import load_endpoint_registry
from lawful_anomaly_screening.settings import REPO_ROOT, load_settings


def test_config_loading():
    settings = load_settings()
    assert settings.baseline_path == REPO_ROOT / "config/baselines/baseline_v1_5_default.json"
    assert settings.logging_config_path == REPO_ROOT / "config/logging/logging.yaml"
    assert settings.export_precision_path == REPO_ROOT / "config/exports/precision_tiers.json"
    assert settings.endpoints_path == REPO_ROOT / "config/sources/endpoints.json"
    assert settings.preprocessing_config_path == REPO_ROOT / "config/sources/preprocessing.json"


def test_endpoint_keys_exist():
    endpoints = json.loads((REPO_ROOT / "config/sources/endpoints.json").read_text(encoding="utf-8"))
    assert endpoints["primary"] == "earth_search"
    assert endpoints["fallbacks"] == ["cdse", "landsatlook"]
    assert {"earth_search", "cdse", "landsatlook"} <= set(endpoints)


def test_endpoint_registry_exposes_primary_and_fallbacks():
    registry = load_endpoint_registry()
    assert registry.primary_endpoint.endpoint_id == "earth_search"
    assert [endpoint.endpoint_id for endpoint in registry.fallback_endpoints] == ["cdse", "landsatlook"]


def test_relative_env_overrides_are_repo_anchored(monkeypatch):
    monkeypatch.setenv("LAWFUL_ANOMALY_ENDPOINTS_PATH", "config/sources/endpoints.json")
    monkeypatch.setenv("LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH", "config/sources/preprocessing.json")
    monkeypatch.setenv("LAWFUL_ANOMALY_BASELINE_PATH", "config/baselines/baseline_v1_5_default.json")

    settings = load_settings()

    assert settings.endpoints_path == REPO_ROOT / "config/sources/endpoints.json"
    assert settings.preprocessing_config_path == REPO_ROOT / "config/sources/preprocessing.json"
    assert settings.baseline_path == REPO_ROOT / "config/baselines/baseline_v1_5_default.json"
