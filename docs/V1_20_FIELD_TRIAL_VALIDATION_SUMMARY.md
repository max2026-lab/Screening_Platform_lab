# V1.20 Field Trial Validation Summary

## Inherited release

- v1.19.0

## Base commit

- `ab65bb39e6d939d5cf67a9644623f57debc4274c`

## Baseline tag

- `baseline-v1.20-reviewer-rubric-cli-evidence-2026-05-12`

## V1.20 branch

- `docs/v1.20-field-trial-validation-summary`

## Validation scope

- documents the V1.20 local field-trial validation summary for the reviewer-facing closeout workflow
- confirms the trial remains offline and operator-runbook driven
- records the known local trial-path caveat for export bundle verification
- records the known non-blocking artifact inventory warning during local trial layouts
- preserves the existing V1.20 scope disclaimer that synthetic non-zero-candidate AOIs validate workflow plumbing only and do not prove detector quality

## Field-trial summary

- V1.20 field-trial validation is centered on operator workflow confirmation, not model-quality re-evaluation
- export bundle verification must be run from repo root when `export-create` returns a relative `bundle_manifest_path`
- using `--export-root "$trialRoot\exports"` with a relative manifest path is invalid because it resolves to `.trial-v1-20\exports\exports\reports\...`
- `operator-artifact-inventory --root .trial-v1-20` may warn when export artifacts live under repo `exports/reports` instead of inside `.trial-v1-20`
- that inventory warning is non-blocking when `export-bundle-verify` passes for the actual report bundle

## Operator commands

```powershell
lawful-anomaly export-bundle-verify --bundle-manifest-path exports/reports/<name>.zip.manifest.json --export-root .
lawful-anomaly operator-artifact-inventory --root .trial-v1-20
```

## Acceptance notes

- field-trial validation is acceptable when bundle verification passes against the actual exported report bundle
- artifact inventory warnings caused only by the split between `.trial-v1-20` evidence and repo `exports/reports` output are non-blocking
- no network, GitHub, database, provider, scoring, calibration, or schema changes are introduced by this documentation update

## Rollback point

- v1.19.0

## Next step

- keep this summary with the V1.20 release package so operators have one place to reference the field-trial caveats before final release tagging
