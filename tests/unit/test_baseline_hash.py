import json
from pathlib import Path


def test_baseline_shape():
    data = json.loads(Path("config/baselines/baseline_v1_5_default.json").read_text(encoding="utf-8"))
    assert data["processing_baseline_id"] == "baseline_v1_5_default"
    assert data["score_formula_version"] == "v1.5.1-phase0"
    assert data["execution"]["tile_size"] == 320
    assert data["execution"]["mode"] == "synchronous"
    assert data["execution"]["persistence"] == "sqlite"
    assert data["scene_cloud_filter"] == {"operator": "lt", "value": 30}
    assert data["protected_area_sources"] == ["UNESCO", "WDPA"]
    assert data["deferred_automated_scoring"]["excluded_from_automated_scoring"] is True
