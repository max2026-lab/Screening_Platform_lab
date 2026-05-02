# V1.4 Release Notes — Scope Lock

This document locks the V1.4 release candidate scope, release gate, limitations, rollback point, and next step.

## Release Candidate Commit

`983b4225088e0e29a08f346aae3b92e8344fba20`

## Baseline Tags

- `baseline-v1.4-real-stac-aoi-bbox-smoke-2026-05-02`
- `baseline-v1.4-real-stac-aoi-bbox-release-script-2026-05-02`

## Inherited Release

- `v1.3.0`

## Validation Commands

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## Exact V1.4 Changes

- Real AOI GeoJSON bbox is wired into active real STAC metadata-only `/search`.
- Bbox format is `[min_lon, min_lat, max_lon, max_lat]`.
- Bbox is included in STAC POST payload when real STAC is explicitly active.
- Bbox is preserved in manifest `query_parameters`.
- Active real STAC fails clearly if AOI bbox is unavailable.
- AOI bbox extraction supports `Polygon`, `MultiPolygon`, `Feature`, and `FeatureCollection`.
- AOI bbox extraction validates coordinate pairs and rejects malformed / non-numeric coordinates clearly with `invalid AOI coordinate`.
- Normal tests remain mocked / offline.
- V1.4 release verification script added.

## Exact Unchanged Behavior

- Simulated / offline scene discovery remains default.
- Real STAC endpoint remains inactive by default.
- No raster download.
- No scoring changes.
- No threshold changes.
- No candidate generation changes.
- No calibration changes.
- No DB schema changes.
- No UI changes.
- No paid provider execution required.

## Exact Supported V1.4 Operator Workflow

Default offline flow remains unchanged.

Optional live STAC smoke requires:
1. Explicit active endpoint config (`active: true`, `metadata_only: true`).
2. Valid AOI GeoJSON.
3. Network connectivity.
4. `create-run` verifies discovered scenes, manifest hash, and bbox query context.

## Exact Release Gate

- pytest must pass.
- V1.4 release verification script must pass.
- V1.3 release verification script must pass.
- V1.2 release verification script must pass.
- V1.1 no-candidates verification script must pass.
- Phase 28 full release evidence manifest must pass.
- `git status` must be clean.
- `git remote -v` must be token-free.

## Exact Rollback Point

`baseline-v1.4-real-stac-aoi-bbox-release-script-2026-05-02`

## Exact Next Step After This Doc

1. Clean-machine V1.4 smoke validation.
2. If clean, create and push `v1.4.0` tag.
3. Publish GitHub Release `v1.4.0`.
