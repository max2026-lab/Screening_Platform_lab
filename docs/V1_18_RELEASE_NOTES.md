# V1.18 Release Notes — Review Package Readiness Check

## Inherited release

- v1.17.0

## Base commit

- `4a43ac6f922eb7bfccabcb06eef24209554fa271`

## Baseline tag

- `baseline-v1.17-operator-artifact-inventory-2026-05-10`

## V1.18 branch

- `feature/v1.18-review-package-readiness-check`

## Exact V1.18 changes

- added offline CLI:
  `lawful-anomaly review-package-readiness-check --run-id <run_id> [--artifact-root <path>] [--output-dir <path>] [--format json|markdown|both]`
- gives the operator a deterministic readiness report before exposing a screening run to analyst review
- `--run-id` is required
- `--artifact-root` is optional; if provided, artifact files are inspected read-only
- `--output-dir` controls where report artifacts are written (default: `.review-package-readiness/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- writes report artifacts under `<output-dir>/`:
  - `review_package_readiness_check.json`
  - `review_package_readiness_check.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the generated JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- stable JSON formatting, stable ordering, no wall-clock timestamp in hashed content
- checks include:
  - **Run metadata**: existence, status, AOI hash/path, dates, legal gate, source endpoint id, manifest hash
  - **Legal/safety**: fails if legal gate decision is not `pass`; warns if legal gate metadata is missing or malformed
  - **Candidate/review queue**: candidate count, review queue count, top candidate id; fails if run is completed/review_ready but has neither candidates nor an allowed zero-candidate export path; warns if candidates exist but review queue is empty
  - **Candidate readiness**: warns if score or score breakdown is missing; warns if possible_duplicate flags are true; warns on geofence hits
  - **Artifact readiness** (if `--artifact-root` provided): root exists/directory/readable; file counts for JSON, Markdown, images, GeoJSON, ZIP; detection of incomplete/temp files
  - **Export separation signals** (if `--artifact-root` provided): warns if public/obfuscated files contain exact/precise/reviewer_only in filename; warns if reviewer-only and public artifacts appear mixed
- result status:
  - `pass` if required run/legal/candidate checks pass and there are no warnings
  - `warn` if required checks pass but warnings exist
  - `fail` if run missing, legal gate blocks review, DB read fails, artifact-root missing/not directory, or required review-readiness invariants fail
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not require network
- does not call GitHub
- does not require provider calls
- does not mutate database
- does not start workers
- does not build or rewrite review packages
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify operator-artifact-inventory behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior
- does not modify V1.17 operator artifact inventory behavior

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

## Validation commands

```
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

- v1.17.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.18 smoke, then tag v1.18.0 and publish GitHub Release if clean
