# V1.20 Release Notes — Review Closeout Package

## Inherited release

- v1.19.0

## Base commit

- `5b01e739a7018a892cf68313ca74a9da2b582fc1`

## Baseline tag

- `baseline-v1.19-reviewer-handoff-package-2026-05-10`

## V1.20 branch

- `feature/v1.20-review-closeout-package`

## Exact V1.20 changes

- added offline CLI:
  `lawful-anomaly review-closeout-package --run-id <run_id> [--output-dir <path>] [--format json|markdown|both] [--require-all-resolved]`
- creates a deterministic post-review closeout package before export, showing whether reviewer decisions are complete enough to proceed
- `--run-id` is required
- `--output-dir` controls where report artifacts are written (default: `.review-closeout/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- `--require-all-resolved` causes failure if any unresolved candidates remain
- writes report artifacts under `<output-dir>/`:
  - `review_closeout_package.json`
  - `review_closeout_package.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- stable JSON formatting, stable ordering, no wall-clock timestamp in hashed content
- package content includes:
  - **Run summary**: run_id, status, AOI hash/path, dates, legal gate decision, source endpoint id, source scene manifest hash
  - **Review closeout summary**: total candidate count, counts by state (pending_review, watch, rejected, approved_for_archive_quote, other), review action count
  - **Decision completeness**: unresolved candidate IDs up to cap 50; unresolved means pending_review/watch; warns by default, fails if `--require-all-resolved`
  - **Export readiness**: approved/exportable candidate count; warns if zero approved but candidates exist; warns if possible_duplicate on approved candidates; warns if previous export records exist
- safety: candidate rows include only candidate_id, current_state, possible_duplicate, and score; no exact coordinates, geometry, bounds, or centroids
- result status:
  - `pass` if run/legal checks pass, no warnings, and closeout is complete enough
  - `warn` if required checks pass but warnings exist
  - `fail` if run missing, DB read fails, legal gate blocks, or `--require-all-resolved` has unresolved candidates
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not require network
- does not call GitHub
- does not require provider calls
- does not mutate database
- does not start workers
- does not create exports
- does not change review decisions
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify operator-artifact-inventory behavior
- does not modify review-package-readiness behavior
- does not modify reviewer-handoff behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior
- does not modify V1.17 operator artifact inventory behavior
- does not modify V1.18 review package readiness behavior
- does not modify V1.19 reviewer handoff behavior

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
- V1.19 reviewer handoff package remains available

## Validation commands

```
uv run pytest tests/integration/test_review_closeout_package_cli.py
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

- V1.20 targeted review closeout package tests must pass
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

- v1.19.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.20 smoke, then tag v1.20.0 and publish GitHub Release if clean
