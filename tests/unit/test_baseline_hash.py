import json
from pathlib import Path


def test_baseline_shape():
    data = json.loads(Path("config/baselines/baseline_v1_5_default.json").read_text(encoding="utf-8"))
    assert data["execution"]["tile_size"] == 320
