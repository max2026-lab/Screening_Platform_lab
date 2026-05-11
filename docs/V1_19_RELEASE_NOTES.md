# V1.19 Release Notes — Reviewer Handoff Package

## Inherited release

- v1.18.0

## Base commit

- `ec14ea614c3db1ab841b8c40dd34502c36af5415`

## Baseline tag

- `baseline-v1.18-review-package-readiness-check-2026-05-10`

## V1.19 branch

- `feature/v1.19-reviewer-handoff-package`

## Exact V1.19 changes

- added offline CLI:
  `lawful-anomaly reviewer-handoff-package --run-id <run_id> [--artifact-root <path>] [--output-dir <path>] [--format json|markdown|both] [--limit <n>]`
- creates a deterministic reviewer handoff package after V1.18 readiness passes/warns, without changing review decisions or exporting sensitive data
- `--run-id` is required
- `--artifact-root` is optional; if provided, artifact files are inspected read-only
- `--output-dir` controls where report artifacts are written (default: `.reviewer-handoff/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- `--limit` caps queued candidate rows (default: `25`)
- writes report artifacts under `<output-dir>/`:
  - `reviewer_handoff_package.json`
  - `reviewer_handoff_package.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the generated JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- stable JSON formatting, stable ordering, no wall-clock timestamp in hashed content
- package content includes:
  - **Run summary**: run_id, status, AOI hash/path, dates, legal gate decision, source endpoint id, source scene manifest hash
  - **Readiness status**: internally reuses V1.18 review package readiness logic in a read-only way; includes readiness status, warnings, and failures; if readiness fails, handoff status is fail
  - **Review queue summary**: candidate count, review queue count, pending_review/watch/rejected/approved counts, top candidate id, queued candidate ids up to `--limit`
  - **Queued candidate rows**: candidate_id, current_state, possible_duplicate, candidate_score, parent_tile_score
  - **Artifact references** (if `--artifact-root` provided): artifact paths, counts, temp/incomplete detection, safety warnings
- result status:
  - `pass` if readiness passes and there are no warnings
  - `warn` if readiness passes/warns and warnings exist
  - `fail` if run missing, DB read fails, readiness fails, or artifact-root is provided but missing/not directory
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not require network
- does not call GitHub
- does not require provider calls
- does not mutate database
- does not start workers
- does not create/rewrite review packages
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify operator-artifact-inventory behavior
- does not modify review-package-readiness behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior
- does not modify V1.17 operator artifact inventory behavior
- does not modify V1.18 review package readiness behavior

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
- V1.11 release evidence index verifier remains available
- V1.12 release evidence index exporter remains available
- V1.13 release evidence index export verifier remains available
- V1.14 release evidence index export smoke remains available
- V1.15 release evidence export smoke report remains available
- V1.16 operator readiness check remains available
- V1.17 operator artifact inventory remains available
- V1.18 review package readiness check remains available

## Validation commands

```
uv run pytest tests/integration/test_reviewer_handoff_package_cli.py
uv run pytest tests/integration/test_review_package_readiness_check_cli.py
uv run pytest tests/integration/test_operator_artifact_inventory_cli.py
uv run pytest tests/integration/test_operator_readiness_check_cli.py
uv run pytest tests/integration/test_release_evidence_index_export_smoke_report_cli.py
uv run pytest tests/integration/test_release_evidence_index_export_smoke_cli.py
uv run pytest tests/integration/test_release_evidence_index_export_verify_cli.py
uv run pytest tests/integration/test_release_evidence_index_export_cli.py
uv run pytest tests/integration/test_release_evidence_index_verify_cli.py
uv run pytest tests/integration/test_release_evidence_verify_cli.py
uv run pytest tests/integration/test_export_bundle_verify_batch_cli.py
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
```

## Release gate

- V1.19 targeted reviewer handoff package tests must pass
- V1.18 targeted review package readiness check tests must pass
- V1.17 targeted operator artifact inventory tests must pass
- V1.16 targeted operator readiness check tests must pass
- V1.15 targeted release evidence export smoke report tests must pass
- V1.14 targeted release evidence index export smoke tests must pass
- V1.13 targeted release evidence index export verify tests must pass
- V1.12 targeted release evidence index export tests must pass
- V1.11 targeted release evidence index verifier tests must pass
- V1.10 targeted release evidence verifier tests must pass
- V1.9 batch tests must pass
- V1.8 targeted tests must pass
- export repository tests must pass
- pytest must pass
- git status must be clean
- git remote must be token-free

## Rollback point

- v1.18.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.19 smoke, then tag v1.19.0 and publish GitHub Release if clean
