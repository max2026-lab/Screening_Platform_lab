# V1.11 Release Notes — Release Evidence Index Verifier

## Inherited release

- v1.10.0

## Base commit

- `5f276d40c0f549948a527be8a51d14f3e7c8b629`

## Baseline tag

- `baseline-v1.10-release-evidence-verifier-2026-05-09`

## V1.11 branch

- `feat/v1.11-release-evidence-index-verifier`

## Exact V1.11 changes

- added offline CLI:
  `lawful-anomaly release-evidence-index-verify`
- verifies multiple downloaded release evidence directories from disk
- recursively discovers evidence directories under `--evidence-root`
- supports explicit `--evidence-list` text files
- reuses V1.10 `release-evidence-verify` logic
- supports `--output json|markdown`
- supports `--fail-fast`
- returns aggregate pass/fail JSON
- reports `evidence_dir_count`, `passed_count`, `failed_count`, `checked_file_count`
- emits deterministic `index_hash`
- detects duplicate evidence-list paths
- fails clearly when no evidence directories are found
- fails clearly when both `evidence-root` and `evidence-list` are supplied
- does not require DB access
- does not require network
- does not call GitHub
- does not rerun Phase 28

## Unchanged behavior

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
- V1.7 sidecar manifest generation remains unchanged
- V1.8 single-bundle verifier remains available
- V1.9 batch verifier remains available
- V1.10 single release evidence verifier remains available

## Validation commands

```
uv run pytest tests/integration/test_release_evidence_index_verify_cli.py
uv run pytest tests/integration/test_release_evidence_verify_cli.py
uv run pytest tests/integration/test_export_bundle_verify_batch_cli.py
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_11_release_evidence_index_verifier_release.ps1
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

## Release gate

- V1.11 targeted release evidence index verifier tests must pass
- V1.10 targeted release evidence verifier tests must pass
- V1.9 batch tests must pass
- V1.8 targeted tests must pass
- export repository tests must pass
- pytest must pass
- V1.11 release verification must pass
- V1.10/V1.9/V1.8/V1.7/V1.6/V1.5/V1.4/V1.3/V1.2/V1.1 verifications must pass
- Phase 28 full release evidence manifest must pass
- clean-machine V1.11 smoke must pass before v1.11.0 tag
- git status must be clean
- git remote must be token-free

## Rollback point

- v1.10.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.11 smoke, then tag v1.11.0 and publish GitHub Release if clean
