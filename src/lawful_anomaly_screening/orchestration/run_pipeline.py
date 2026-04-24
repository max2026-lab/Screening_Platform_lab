from __future__ import annotations

from pathlib import Path
from .scaffold_run import scaffold_run_for_run_id

def execute_run(
    db_path: Path | str,
    *,
    run_id: str,
    cache_root: Path | str = Path("data/cache"),
) -> dict:
    # Phase 4: Use the existing deterministic scaffold run path
    return scaffold_run_for_run_id(
        db_path,
        run_id=run_id,
        cache_root=cache_root,
    )
