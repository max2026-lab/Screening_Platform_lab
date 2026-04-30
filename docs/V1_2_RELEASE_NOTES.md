# V1.2 Release Notes and Scope Lock

This document defines the V1.2 release candidate scope, validation gate, known limitations, rollback point, and next action. It is intended as an operator contract for the V1.2 release candidate, not a marketing summary.

## Release Candidate

- V1.2 release candidate commit: `0df4406b9a7ae4570c00dfd640649e3ac26532b1`
- V1.2 baseline tags:
  - `baseline-v1.2-run-summary-command-2026-04-29`
  - `baseline-v1.2-run-summary-release-script-2026-04-29`
- Inherited V1.1 release tag:
  - `v1.1.0`
- Validation commands:
  - `powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1`
  - `powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1`
  - `powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite`
- Evidence output path: `.release-evidence\phase28-full-release-evidence-manifest`

## What Changed in V1.2

V1.2 adds exactly these changes on top of V1.1.0:

- Added `lawful-anomaly run-summary --run-id <run_id>`
- `run-summary` reads persisted data only (no provider/network calls)
- `run-summary` returns JSON
- Candidate-backed runs show `candidate_count > 0` and `top_candidate_id` present
- Zero-candidate completed/review_ready runs show `candidate_count = 0` and `top_candidate_id` null
- Latest export fields (`latest_export_record_id`, `latest_export_artifact_path`) appear after `export-create`
- Missing run id fails with `run not found`
- V1.2 release verification script added: `scripts\verify_v1_2_run_summary_release.ps1`

## Unchanged Behavior

V1.2 explicitly does not change:

- Scoring
- Thresholds
- Candidate generation
- Provider behavior
- Calibration logic
- DB schema
- UI
- Live paid-provider execution requirements

## Supported V1.2 Operator Workflow

The supported V1.2 operator workflow is:

1. AOI GeoJSON (UTF-8 no BOM)
2. `lawful-anomaly create-run`
3. `lawful-anomaly execute-run`
4. `lawful-anomaly run-summary --run-id <run_id>`
5. Export restricted report

## Unsupported and Out of Scope

V1.2 explicitly does not include:

- Production cloud deployment
- UI polish/review dashboard as product surface
- Provider expansion beyond existing mocks/scaffolded flows
- Live paid-provider network execution as required path
- Automated calibration training from labels
- Scoring recalibration
- Threshold changes
- DB schema changes
- Multi-user auth/roles
- Queue/worker architecture
- Background scheduling

## Release Gate

V1.2 is releasable only when all of these conditions are true:

- pytest must pass
- V1.2 release verification script must pass
- V1.1 no-candidates verification script must pass
- Phase 28 full release evidence manifest must pass
- git status must be clean
- git remote must be token-free

## Known Limitations

- local/operator-run release
- evidence is local and ignored under `.release-evidence`
- no production hosting guarantee
- no claim of real-provider paid archive delivery unless separately configured and validated
- no automated model retraining

## Rollback Point

Rollback to the exact baseline tag:

`baseline-v1.2-run-summary-release-script-2026-04-29`

## Next Step

Run clean-machine V1.2 smoke validation, then create the `v1.2.0` tag if clean.
