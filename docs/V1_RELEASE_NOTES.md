# V1 Release Notes and Scope Lock

This document defines the V1 release candidate scope, validation gate, known limitations, rollback point, and next action. It is intended as an operator contract for the V1 release candidate, not a marketing summary.

## Release Candidate

- V1 release candidate commit: `a4ea22a1da1ea776623eac0ecd52faa9a8e707ed`
- V1 baseline tag: `baseline-phase28-full-release-evidence-manifest-2026-04-28`
- Validation command: `powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite`
- Evidence output path: `.release-evidence\phase28-full-release-evidence-manifest`

## Supported Capabilities

V1 includes exactly these supported capabilities:

- operator scaffold/run flow
- legal/geofence blocking
- composite metadata foundation
- reproducibility checks
- candidate scoring explainability
- export audit manifest
- acceptance KPI gate
- paid archive escalation path
- calibration evidence pack
- calibration policy versioning
- calibration label pack
- label pack audit manifest
- calibration label artifact export
- calibration label artifact verification
- calibration artifact registry
- registry snapshot export
- registry snapshot verification
- registry snapshot diff
- registry snapshot diff evidence export
- registry snapshot diff evidence verification
- registry diff acceptance gate
- calibration sign-off evidence bundle
- full release verification chain
- full release evidence manifest

## Unsupported and Out of Scope

V1 explicitly does not include:

- production cloud deployment
- UI polish/review dashboard as product surface
- provider expansion beyond existing mocks/scaffolded flows
- live paid-provider network execution as required path
- automated calibration training from labels
- scoring recalibration
- threshold changes
- DB schema changes
- multi-user auth/roles
- queue/worker architecture
- background scheduling

## Release Gate

V1 is releasable only when all of these conditions are true:

- Phase 28 must pass on clean main
- git remote must be token-free
- git status must be clean after validation
- Phase 27 full chain must pass inside Phase 28
- pytest must pass
- Phase 5 through Phase 26 release scripts must pass

## Known Limitations

- local/operator-run release
- evidence is local and ignored under `.release-evidence`
- no production hosting guarantee
- no claim of real-provider paid archive delivery unless separately configured and validated
- no automated model retraining

## Rollback Point

Rollback to the exact baseline tag:

`baseline-phase28-full-release-evidence-manifest-2026-04-28`

## Next Step

Run clean-machine smoke validation, then create the `v1.0.0` tag if clean.
