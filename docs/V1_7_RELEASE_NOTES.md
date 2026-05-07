# V1.7 Release Notes and Scope Lock

## Release Candidate Commit

- `576799e38fcf3a96166be873cc9b93698119ee61`

## Inherited Release

- `v1.6.0`

## Baseline Tags

- `baseline-v1.7-report-bundle-manifest-index-2026-05-06`
- `baseline-v1.7-report-bundle-manifest-release-verification-2026-05-06`

## Exact V1.7 Changes

- `report_pdf` exports now create a deterministic sidecar manifest JSON
  - sidecar filename is `<bundle_name>.manifest.json`
  - returned export payload includes non-DB `bundle_manifest_path`
  - sidecar `schema_version` is `v1.7_report_bundle_manifest`
  - sidecar includes run/export/audience/precision metadata
  - sidecar includes `artifact_name`, `artifact_path`, `bundle_name`, `bundle_path`
  - sidecar includes `bundle_sha256` and `bundle_members`
  - sidecar includes `audit_manifest_hash`
  - sidecar includes `source_endpoint_id` and `source_scene_manifest_hash`
  - sidecar includes `candidate_count`
  - sidecar `files` list includes:
    - `report_markdown`
    - `bundle_zip`
    - `audit_manifest`
    - `checksum_manifest`
  - sidecar validates SHA256 hashes for report, ZIP, `audit_manifest.json`, and `SHA256SUMS.txt`
  - zero-candidate restricted reports also create sidecar manifests
  - non-report audiences do not create sidecar manifests
  - sidecar does not include `centroid`, `clipped_geometry`, `bounds`, or `coordinates`

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
- V1.6 ZIP bundle behavior remains unchanged

## Validation Commands

```powershell
uv run pytest tests/integration/test_export_repository.py
uv run pytest

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

- export repository tests: passed
- pytest: 348 passed
- V1.7 verification: passed
- V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications: passed
- Phase 28 full release evidence manifest: passed

## Release Gate

- export repository tests must pass
- pytest must pass
- V1.7 release verification must pass
- V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- clean-machine V1.7 smoke must pass before `v1.7.0` tag
- `git status` must be clean
- `git remote` must be token-free

## Rollback Point

- `baseline-v1.7-report-bundle-manifest-release-verification-2026-05-06`

## Next Step

- clean-machine V1.7 smoke validation, then `v1.7.0` tag if clean
