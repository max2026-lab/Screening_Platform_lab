# V1.9 Release Notes — Export Bundle Batch Verification CLI

## Base Commit

`f94f1221250324acbeb1f9ffb7636d9572487493`

## Inherited Release

- v1.8.0

## Baseline Tag

- `baseline-v1.8-release-notes-scope-lock-2026-05-07`

## V1.9 Branch

- `feat/v1.9-export-bundle-verify-batch`

## Exact V1.9 Changes

- Added offline batch CLI:
  - `lawful-anomaly export-bundle-verify-batch`
- Verifies every `*.zip.manifest.json` in a reports folder
- Verifies explicit sidecar paths from manifest-list text file
- Reuses V1.8 single-bundle verifier
- Supports `--reports-dir`
- Supports `--manifest-list`
- Supports `--export-root`
- Supports `--output json|markdown`
- Supports `--fail-fast`
- Returns aggregate pass/fail JSON
- Reports `manifest_count`, `passed_count`, `failed_count`, `checked_file_count`
- Fails clearly when no manifests are found
- Fails clearly when both `--reports-dir` and `--manifest-list` are supplied
- Does not require DB access
- Does not require network
- Does not rerun `export-create`

## Exact Unchanged Behavior

- No DB schema changes
- No scoring changes
- No threshold changes
- No candidate generation changes
- No calibration changes
- No provider/STAC changes
- No live smoke changes
- No UI changes
- No paid provider execution required
- V1.5 live STAC smoke remains manual opt-in only
- Normal pytest remains offline/mocked
- V1.6 ZIP bundle behavior remains unchanged
- V1.7 sidecar manifest generation remains unchanged
- V1.8 single-bundle verifier remains available

## Validation Commands

```powershell
uv run pytest tests/integration/test_export_bundle_verify_batch_cli.py
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_9_export_bundle_verify_batch_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_8_export_bundle_verify_cli_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_7_report_bundle_manifest_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_6_export_bundle_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_5_live_stac_metadata_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## Release Gate

- V1.9 targeted batch tests must pass
- V1.8 targeted tests must pass
- Export repository tests must pass
- Pytest must pass
- V1.9 release verification must pass
- V1.8/V1.7/V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- Clean-machine V1.9 smoke must pass before v1.9.0 tag
- Git status must be clean
- Git remote must be token-free

## Rollback Point

- `v1.8.0`

## Next Step

After branch validation, merge to main, tag baseline, run clean-machine V1.9 smoke, then tag v1.9.0 and publish GitHub Release if clean.
