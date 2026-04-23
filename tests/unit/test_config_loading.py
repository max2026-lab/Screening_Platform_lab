import json
from pathlib import Path

from lawful_anomaly_screening.sources.earth_search import load_endpoint_registry
from lawful_anomaly_screening.settings import load_settings


def test_config_loading():
    assert load_settings().baseline_path.name == "baseline_v1_5_default.json"


def test_endpoint_keys_exist():
    endpoints = json.loads(Path("config/sources/endpoints.json").read_text(encoding="utf-8"))
    assert endpoints["primary"] == "earth_search"
    assert endpoints["fallbacks"] == ["cdse", "landsatlook"]
    assert {"earth_search", "cdse", "landsatlook"} <= set(endpoints)


def test_endpoint_registry_exposes_primary_and_fallbacks():
    registry = load_endpoint_registry()
    assert registry.primary_endpoint.endpoint_id == "earth_search"
    assert [endpoint.endpoint_id for endpoint in registry.fallback_endpoints] == ["cdse", "landsatlook"]
