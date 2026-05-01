# V1.3 Release Notes and Scope Lock

This document locks the V1.3 release candidate scope, exact changes, unchanged behavior, operator workflow, release gate, rollback point, and next step. It is contractual, not marketing.

## Release Candidate Commit

`8dad921d9893953bad966253e9985b243795a8d2`

## Baseline Tags

- `baseline-v1.3-real-stac-provider-smoke-2026-04-30`
- `baseline-v1.3-real-stac-release-script-2026-04-30`

## Inherited Release

`v1.2.0`

## Exact V1.3 Changes

- Added explicit real STAC metadata-only provider smoke path.
- Earth Search endpoint metadata added with `active: false` by default.
- Active real STAC behavior requires explicit endpoint config opt-in.
- STAC query uses `/search` metadata request only.
- No raster assets are downloaded.
- Normal tests remain mocked/offline.
- STAC item normalization preserves `provider_item_id`, `collection`, `acquired_at`, `cloud_cover` where available.
- Manifest JSON preserves STAC `query_parameters` and `collection_summary`.
- Manifest hash includes STAC query context and normalized scene list.
- `discovered_scenes` persistence remains on existing schema.
- Missing STAC `cloud_cover` remains `null` in manifest JSON while DB insert uses legacy fallback only.
- V1.3 mocked release verification script added.

## Exact Unchanged Behavior

- Simulated/offline scene discovery remains default.
- No scoring changes.
- No threshold changes.
- No candidate generation changes.
- No calibration changes.
- No DB schema changes.
- No UI changes.
- No paid provider execution required.
- No raster download.

## Exact Supported V1.3 Operator Workflow

Default offline flow remains unchanged. Optional live STAC smoke requires:
1. Active endpoint config (`earth_search.active: true`) set by operator.
2. Network connectivity available.
3. `create-run` verifies discovered scenes and manifest hash contain real STAC context.

If `active` remains `false` (default), all behavior is identical to V1.2.

## Validation Commands

Run these from repo root in order:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

All four must pass.

## Release Gate

- `pytest` must pass.
- V1.3 release verification script must pass.
- V1.2 release verification script must pass.
- V1.1 no-candidates verification script must pass.
- Phase 28 full release evidence manifest must pass.
- `git status` must be clean.
- `git remote -v` must be token-free.

## Rollback Point

`baseline-v1.3-real-stac-release-script-2026-04-30`

## Next Step After This Document

Clean-machine V1.3 smoke validation, then `v1.3.0` tag if clean.
