# V1.10 Release Notes — Release Evidence Verifier CLI

## Inherited Release

- `v1.9.0`

## Base Commit

- `97f2364536e38b8ca09ac1c5fc70d3497a4ae8d0`

## Baseline Tag

- `baseline-v1.9-export-bundle-verify-batch-2026-05-08`

## V1.10 Branch

- `feat/v1.10-release-evidence-verifier`

## Exact V1.10 Changes

- Added offline CLI:
  `lawful-anomaly release-evidence-verify`
- Verifies downloaded release evidence artifacts from disk
- Verifies `full_release_evidence_manifest.json` parses and has release evidence structure
- Verifies `full_release_evidence_manifest.md` is recognizable release evidence markdown
- Verifies `SHA256SUMS.txt` hashes for json and md evidence files
- Supports `--evidence-dir`
- Supports `--output json|markdown`
- Returns deterministic pass/fail JSON
- Returns non-zero on failed verification
- Does not require DB access
- Does not require network
- Does not call GitHub
- Does not rerun Phase 28

## Unchanged Behavior

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
- V1.9 batch verifier remains available

## Validation Commands

```powershell
uv run pytest tests/integration/test_release_evidence_verify_cli.py
uv run pytest tests/integration/test_export_bundle_verify_batch_cli.py
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_10_release_evidence_verifier_release.ps1
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

- V1.10 targeted release evidence verifier tests must pass
- V1.9 batch tests must pass
- V1.8 targeted tests must pass
- Export repository tests must pass
- Pytest must pass
- V1.10 release verification must pass
- V1.9/V1.8/V1.7/V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- Clean-machine V1.10 smoke must pass before `v1.10.0` tag
- Git status must be clean
- Git remote must be token-free

## Rollback Point

- `v1.9.0`

## Next Step

After branch validation, merge to main, tag baseline, run clean-machine V1.10 smoke, then tag `v1.10.0` and publish GitHub Release if clean.
