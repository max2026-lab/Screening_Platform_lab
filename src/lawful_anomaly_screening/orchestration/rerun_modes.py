RERUN_MODE_REVIEW_ONLY = "review_only"
RERUN_MODE_EXACT_CACHED = "rerun_exact_cached"
RERUN_MODE_EXACT_RECOMPUTE = "rerun_exact_recompute"
RERUN_MODE_NEW_WINDOW = "rerun_new_window"

VALID_RERUN_MODES = (
    RERUN_MODE_REVIEW_ONLY,
    RERUN_MODE_EXACT_CACHED,
    RERUN_MODE_EXACT_RECOMPUTE,
    RERUN_MODE_NEW_WINDOW,
)

CACHE_STATUS_HIT = "hit"
CACHE_STATUS_PARTIAL = "partial"
CACHE_STATUS_MISS = "miss"


def determine_cache_status(
    required_asset_kinds: list[str],
    cached_asset_rows: list[dict],
) -> str:
    required = tuple(sorted(set(required_asset_kinds)))
    if not required:
        return CACHE_STATUS_HIT

    present_asset_kinds = {
        row["asset_kind"]
        for row in cached_asset_rows
        if row["asset_kind"] in required
    }
    if present_asset_kinds == set(required):
        return CACHE_STATUS_HIT
    if present_asset_kinds:
        return CACHE_STATUS_PARTIAL
    return CACHE_STATUS_MISS


def build_rerun_plan(
    *,
    run_id: str,
    rerun_mode: str,
    required_asset_kinds: list[str],
    cached_asset_rows: list[dict],
) -> dict:
    if rerun_mode not in VALID_RERUN_MODES:
        raise ValueError(f"unsupported rerun mode: {rerun_mode}")

    cache_status = determine_cache_status(required_asset_kinds, cached_asset_rows)
    reuse_cached_assets = rerun_mode == RERUN_MODE_EXACT_CACHED and cache_status == CACHE_STATUS_HIT

    return {
        "run_id": run_id,
        "rerun_mode": rerun_mode,
        "required_asset_kinds": list(sorted(set(required_asset_kinds))),
        "cache_status": cache_status,
        "reuse_cached_assets": reuse_cached_assets,
    }
