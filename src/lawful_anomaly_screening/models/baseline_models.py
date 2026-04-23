from dataclasses import dataclass


@dataclass(frozen=True)
class BaselineConfig:
    mode: str = "synchronous"
    persistence: str = "sqlite"
    tile_size: int = 320
    max_cloud_cover_percent: int = 30
