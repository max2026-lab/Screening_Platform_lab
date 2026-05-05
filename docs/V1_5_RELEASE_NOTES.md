# V1.5 Release Notes and Scope Lock

## Release Candidate Commit

- `242aeb36c7f36803343ddab538e103a85f7bbf21`

## Inherited Release

- `v1.4.0`

## Baseline Tags

- `baseline-v1.5-stac-rfc3339-datetime-2026-05-04`
- `baseline-v1.5-live-stac-metadata-smoke-2026-05-04`
- `baseline-v1.5-live-stac-release-verification-2026-05-04`

## Exact V1.5 Changes

- STAC `/search` datetime payload now uses RFC3339 intervals
  - full range: `YYYY-MM-DDT00:00:00Z/YYYY-MM-DDT23:59:59Z`
  - start-only: `YYYY-MM-DDT00:00:00Z/..`
  - end-only: `../YYYY-MM-DDT23:59:59Z`
- manifest `query_parameters.datetime` matches provider payload for hash determinism
- live real Earth Search metadata-only smoke script added
  - live smoke requires `$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"`
  - live smoke verifies:
    - AOI bbox
    - RFC3339 datetime interval
    - `discovered_scenes`
    - `source_scene_manifests`
    - manifest file exists with correct `query_parameters`
    - scene fields (`scene_id`, `acquired_at`, `provider_item_id`, `collection`)
    - no raster files downloaded
- offline V1.5 release verification script added (`scripts/verify_v1_5_live_stac_metadata_release.ps1`)

## Exact Unchanged Behavior

- normal pytest remains offline/mocked
- V1.5 release verification is offline by default
- live Earth Search smoke is manual/operator opt-in only
- simulated/offline discovery remains default
- real STAC endpoint remains inactive by default (`active: false`)
- no raster download
- no scoring changes
- no threshold changes
- no candidate generation changes
- no calibration changes
- no DB schema changes
- no UI changes
- no paid provider execution required

## Validation Commands

```powershell
uv run pytest

powershell -ExecutionPolicy Bypass -File scripts\verify_v1_5_live_stac_metadata_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## Manual Live Smoke Command

```powershell
$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"
powershell -ExecutionPolicy Bypass -File scripts\smoke_live_v1_5_real_stac_metadata.ps1
```

> Live smoke is network-required and manual opt-in only.

## Last Known Validation Summary

- pytest passed (347 passed)
- V1.5 verification passed
- V1.4/V1.3/V1.2/V1.1 verifications passed
- Phase 28 full release evidence manifest passed
- live STAC smoke passed after opt-in
- discovered scenes count: 5

## Release Gate

- pytest must pass
- V1.5 release verification must pass
- V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- clean-machine V1.5 smoke must pass before `v1.5.0` tag
- `git status` must be clean
- `git remote` must be token-free

## Rollback Point

- `baseline-v1.5-live-stac-release-verification-2026-05-04`

## Next Step

- clean-machine V1.5 smoke validation, then `v1.5.0` tag if clean
