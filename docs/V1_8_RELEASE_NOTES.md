# V1.8 Release Notes — Export Bundle Verification CLI

## Release Candidate Commit

`42f4e4a4193f390be4c9003082e179d4a86abefd`

## Inherited Release

- v1.7.0

## Baseline Tag

- `baseline-v1.8-export-bundle-verify-cli-2026-05-07`

## Exact V1.8 Changes

- Added offline operator CLI:
  - `lawful-anomaly export-bundle-verify`
- Verifies existing report ZIP bundle + V1.7 sidecar manifest from disk
- Does not require DB access
- Does not require network
- Does not rerun `export-create`
- Supports:
  - `--bundle-manifest-path`
  - `--export-root`
  - `--output json|markdown`
- Validates sidecar `schema_version`: `v1.7_report_bundle_manifest`
- Validates `bundle_sha256`
- Validates `bundle_members`
- Validates ZIP contains exactly:
  - markdown report artifact
  - `audit_manifest.json`
  - `SHA256SUMS.txt`
- Validates `SHA256SUMS.txt` hashes for report and `audit_manifest.json`
- Validates sidecar `files` hashes for:
  - `report_markdown`
  - `bundle_zip`
  - `audit_manifest`
  - `checksum_manifest`
- Checks sidecar does not contain `centroid`, `clipped_geometry`, `bounds`, or `coordinates`
- Returns JSON/markdown verification result
- Returns non-zero on failed verification
- V1.8 release verification script added:
  - `scripts/verify_v1_8_export_bundle_verify_cli_release.ps1`

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

## Validation Commands

```powershell
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
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

## Last Known Validation Summary

- V1.8 targeted tests passed
- Export repository tests passed
- Pytest passed (355 tests)
- V1.8/V1.7/V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications passed
- Phase 28 full release evidence manifest passed

## Release Gate

- V1.8 targeted tests must pass
- Export repository tests must pass
- Pytest must pass
- V1.8 release verification must pass
- V1.7/V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- Clean-machine V1.8 smoke must pass before v1.8.0 tag
- Git status must be clean
- Git remote must be token-free

## Rollback Point

- `baseline-v1.8-export-bundle-verify-cli-2026-05-07`

## Next Step

Clean-machine V1.8 smoke validation, then v1.8.0 tag and GitHub Release if clean.
