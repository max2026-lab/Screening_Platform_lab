# V1.20 Field Trial Validation Summary

## Current locked baseline

- locked main-line HEAD: `ab65bb39e6d939d5cf67a9644623f57debc4274c`
- latest evidence tag: `baseline-v1.20-reviewer-rubric-cli-evidence-2026-05-12`
- documentation branch for this cleanup: `docs/v1.20-field-trial-validation-summary`

## What was validated

- V1.20 operator workflow
- degenerate one-pixel / zero-area candidate filter
- Field Trial 2 and 3 rechecks
- Field Trials 4-6 zero-candidate exports
- large AOI tile-scaling fix
- Field Trial 8 rerun with tile_count `42` and selected_tile_count `5`
- known-nonzero reference with candidate_count `2`
- landscape-scale candidate flagging
- reviewer rubric guidance
- real CLI evidence for reviewer rubric fields

## Key evidence values

- Field Trial 8 rerun: tile_count `42`, selected_tile_count `5`, candidate_count `0`
- known nonzero reference: tile_count `64`, selected_tile_count `8`, candidate_count `2`
- landscape candidates observed at about `57 ha` and `107 ha`
- reviewer track used for these cases: `landscape_scale_separate_review`

## Current product truth

- bad tiny artifacts are suppressed
- large AOIs scale correctly
- valid large candidates remain visible
- large candidates are flagged
- reviewers get guidance not to fast-track paid imagery solely from automated score

## Known limitations

- no real-world object-scale nonzero field candidate has been captured yet
- landscape-scale candidates are flagged but not suppressed
- scoring thresholds are unchanged
- reviewer rubric is guidance only, not enforcement

## Operator caveats

- if `export-create` returns a relative `bundle_manifest_path`, run `export-bundle-verify` from repo root with `--export-root .`
- do not point `--export-root` at `"$trialRoot\exports"` when the manifest path is already relative to repo `exports/reports`
- `operator-artifact-inventory --root .trial-v1-20` may warn when trial evidence lives under `.trial-v1-20` but export artifacts live under repo `exports/reports`
- that inventory warning is non-blocking when `export-bundle-verify` passes for the actual bundle

## Recommended next build target

- `feat/reviewer-closeout-landscape-scale-decision-path`
- no scoring or suppression change should happen until reviewer decision workflow is clearer
