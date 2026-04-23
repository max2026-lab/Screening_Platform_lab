from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(config_path: Path | str) -> None:
    path = Path(config_path)
    if path.exists():
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.INFO)
