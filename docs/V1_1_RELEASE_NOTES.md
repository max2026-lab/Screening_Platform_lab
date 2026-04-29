# V1.1 Release Notes and Scope Lock

This document defines the V1.1 release candidate scope, validation gate, known limitations, rollback point, and next action. It is intended as an operator contract for the V1.1 release candidate, not a marketing summary.

## Release Candidate

- V1.1 release candidate commit: `28c8542fd7e57f560ec45b55abbca88a6517d25e`
- V1.1 baseline tags:
  - `baseline-v1.1-no-candidates-export-report-2026-04-28`
  - `baseline-v1.1-no-candidates-export-report-release-script-2026-04-28`
  - `baseline-v1.1-operator-manual-2026-04-29`
- Validation commands:
  - `powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1`
  - `powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite`
- Evidence output path: `.release-evidence\phase28-full-release-evidence-manifest`

## What Changed in V1.1

V1.1 adds exactly these changes on top of V1.0.0:

- Completed/review_ready zero-candidate runs can export a restricted markdown report
- Zero-candidate report contains `Candidate count: 0`
- Zero-candidate report contains `## No Exportable Candidates Found`
- Zero-candidate report preserves legal gate and date window metadata
- Zero-candidate export JSON includes `candidates: []`
- Zero-candidate export JSON includes `audit_manifest`
- Unsupported public zero-candidate export still fails
- Existing candidate export behavior remains unchanged
- V1.1 release verification script added: `scripts\verify_v1_1_no_candidates_export_report_release.ps1`
- V1.1 operator manual added: `docs\V1_1_OPERATOR_MANUAL_TARGET_TO_EXPORT.md`

## Unchanged Behavior

V1.1 explicitly does not change:

- Scoring
- Thresholds
- Candidate generation
- Provider behavior
- Calibration logic
- DB schema
- UI
- Live paid-provider execution requirements

## Supported V1.1 Operator Workflow

The supported V1.1 operator workflow is:

1. AOI GeoJSON (UTF-8 no BOM)
2. `lawful-anomaly create-run`
3. `lawful-anomaly execute-run`
4. Inspect `candidate_count`
5. Export restricted report whether `candidate_count` is positive or zero

## Unsupported and Out of Scope

V1.1 explicitly does not include:

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

V1.1 is releasable only when all of these conditions are true:

- pytest must pass
- V1.1 release verification script must pass
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

`baseline-v1.1-operator-manual-2026-04-29`

## Next Step

Run clean-machine V1.1 smoke validation, then create the `v1.1.0` tag if clean.
