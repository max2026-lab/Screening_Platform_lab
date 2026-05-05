# V1.6 Release Notes and Scope Lock

## Release Candidate Commit

- `053c6a134ecf875851c1a4d856615b10e14bbaea`

## Inherited Release

- `v1.5.0`

## Baseline Tags

- `baseline-v1.6-export-bundle-packaging-2026-05-05`
- `baseline-v1.6-export-bundle-release-verification-2026-05-05`

## Exact V1.6 Changes

- `report_pdf` exports now create a deterministic ZIP bundle
  - ZIP bundle filename equals existing `bundle_name`
  - returned export payload includes non-DB `bundle_path`
  - ZIP contains exactly:
    - markdown report artifact
    - `audit_manifest.json`
    - `SHA256SUMS.txt`
  - `SHA256SUMS.txt` validates markdown report and `audit_manifest.json`
  - zero-candidate restricted reports also create bundles
  - non-report audiences do not create report bundles
  - `artifact_path` remains the markdown report path
  - `export_records` schema is unchanged

## Exact Unchanged Behavior

- no DB schema changes
- no scoring changes
- no threshold changes
- no candidate generation changes
- no calibration changes
- no provider/STAC changes
- no live smoke changes
- no UI changes
- no paid provider execution required
- V1.5 live STAC smoke remains manual opt-in only
- normal pytest remains offline/mocked

## Validation Commands

```powershell
uv run pytest tests/integration/test_export_repository.py
uv run pytest

powershell -ExecutionPolicy Bypass -File scripts\verify_v1_6_export_bundle_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_5_live_stac_metadata_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## Last Known Validation Summary

- export repository tests: passed
- pytest: 348 passed
- V1.6 verification: passed
- V1.5/V1.4/V1.3/V1.2/V1.1 verifications: passed
- Phase 28 full release evidence manifest: passed

## Release Gate

- export repository tests must pass
- pytest must pass
- V1.6 release verification must pass
- V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- clean-machine V1.6 smoke must pass before `v1.6.0` tag
- `git status` must be clean
- `git remote` must be token-free

## Rollback Point

- `baseline-v1.6-export-bundle-release-verification-2026-05-05`

## Next Step

- clean-machine V1.6 smoke validation, then `v1.6.0` tag if clean
