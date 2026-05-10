# V1.14 Release Notes — Release Evidence Index Export Round-Trip Smoke

## Inherited release

- v1.13.0

## Base commit

- `6b6d963b1b68d10603f83384a616c852b8a15ee0`

## Baseline tag

- `baseline-v1.13-release-evidence-index-export-verifier-2026-05-10`

## V1.14 branch

- `feature/v1.14-release-evidence-export-roundtrip-smoke`

## Exact V1.14 changes

- added offline CLI:
  `lawful-anomaly release-evidence-index-export-smoke`
- performs a complete local round-trip smoke of V1.12 exporter and V1.13 verifier
- `--evidence-root` points to source evidence directories (not mutated)
- `--output-root` controls where smoke outputs are written
- `--format` supports `json`, `markdown`, `both`, `all` (default `all`)
- for each selected format:
  1. exports release evidence index artifacts into a deterministic format-specific directory
  2. verifies the produced export directory
  3. records pass/fail details per format
- output directory structure:
  - `<output-root>/release-evidence-index-export-smoke/json`
  - `<output-root>/release-evidence-index-export-smoke/markdown`
  - `<output-root>/release-evidence-index-export-smoke/both`
- result JSON includes `schema.version == v1.14.0`, `evidence_root`, `output_root`, `formats_run`, per-format export/verify status, artifact names/hashes, and overall status
- exits nonzero if any format fails export or verify
- prints deterministic JSON result by default
- does not require DB access
- does not require network
- does not call GitHub
- does not mutate source evidence directories
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior

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

## Validation commands

```
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

- v1.13.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.14 smoke, then tag v1.14.0 and publish GitHub Release if clean
