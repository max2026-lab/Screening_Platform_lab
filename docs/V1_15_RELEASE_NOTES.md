# V1.15 Release Notes — Release Evidence Export Smoke Report

## Inherited release

- v1.14.0

## Base commit

- `7f16ac2e9b73f948b97467a5b8e41fb9326e6cb1`

## Baseline tag

- `baseline-v1.14-release-evidence-export-roundtrip-smoke-2026-05-10`

## V1.15 branch

- `feature/v1.15-release-evidence-smoke-report`

## Exact V1.15 changes

- added offline CLI:
  `lawful-anomaly release-evidence-index-export-smoke-report`
- runs the V1.14 round-trip smoke and writes durable evidence report artifacts
- `--evidence-root` points to source evidence directories (not mutated)
- `--output-root` controls where report artifacts are written (required)
- `--format` supports `json`, `markdown`, `both`, `all` (default `all`)
- fails deterministically if `output_root` is the same as or inside `evidence_root`
- writes report artifacts under `<output-root>/release-evidence-index-export-smoke-report/`:
  - `release_evidence_index_export_smoke_report.json`
  - `release_evidence_index_export_smoke_report.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the generated JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- JSON report includes `schema.version == v1.15.0`, `evidence_root`, `output_root`, `formats_run`, embedded V1.14 smoke result, per-format export/verify status, artifact names/hashes, and overall status
- Markdown report summarizes the same result in operator-readable form
- if smoke fails, report artifacts are still written describing the failure, then exits nonzero
- no timestamps in hashed or report content
- stable ordering and stable JSON formatting
- does not require DB access
- does not require network
- does not call GitHub
- does not mutate source evidence directories
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior

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

## Validation commands

```
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

- v1.14.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.15 smoke, then tag v1.15.0 and publish GitHub Release if clean
