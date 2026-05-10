# V1.16 Release Notes — Operator Readiness Check

## Inherited release

- v1.15.0

## Base commit

- `347e096130ea262a1688deeb6590651039e375c5`

## Baseline tag

- `baseline-v1.15-release-evidence-smoke-report-2026-05-10`

## V1.16 branch

- `feature/v1.16-operator-readiness-check`

## Exact V1.16 changes

- added offline CLI:
  `lawful-anomaly operator-readiness-check`
- gives the operator one deterministic local readiness report before attempting real screening/review work
- `--output-dir` controls where report artifacts are written (default: `.operator-readiness/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- writes report artifacts under `<output-dir>/`:
  - `operator_readiness_check.json`
  - `operator_readiness_check.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the generated JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- stable JSON formatting, stable ordering, no wall-clock timestamp in hashed content
- checks include:
  - **Runtime**: Python version, package/import readiness
  - **Git context**: current working directory, `.git` existence, branch/HEAD from local `.git/HEAD` only (no remote calls)
  - **Config/environment**: `APP_ENV`, `LAWFUL_ANOMALY_DB_PATH`, `ARTIFACT_ROOT`, `CACHE_ROOT`, `MANIFEST_ROOT`, `EXPORT_ROOT`, `REVIEWER_EXACT_COORDINATES_ENABLED`, `EXPORT_UNCONFIRMED_COORDINATE_MODE`, `EXPORT_UNCONFIRMED_GRID_KM`, `UP42_ENABLED`
  - **Filesystem readiness**: configured paths exist and are writable (tested via deterministic temp probe in `.readiness-check/`)
  - **Safety config**: rejects `EXPORT_UNCONFIRMED_COORDINATE_MODE=exact`, warns if `EXPORT_UNCONFIRMED_GRID_KM` is not 1 unless pinned, warns if `UP42_ENABLED` is explicitly enabled
  - **Database/Redis**: reports `not_checked` with reason `no existing safe readiness probe` rather than adding broad new infrastructure
- result status:
  - `pass` only if required runtime/config/storage/safety checks pass
  - `warn` if optional items are missing or not checked
  - `fail` if required safety settings are unsafe or required storage paths are missing/not writable
- does not require network
- does not call GitHub
- does not require paid provider credentials
- does not mutate database or source data
- does not start workers
- does not run STAC/live provider smoke
- does not modify release evidence commands
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior

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

## Validation commands

```
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

- v1.15.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.16 smoke, then tag v1.16.0 and publish GitHub Release if clean
