# V1.17 Release Notes — Operator Artifact Inventory

## Inherited release

- v1.16.0

## Base commit

- `54314f94a9c32f75789f522bba36304ef5f9d047`

## Baseline tag

- `baseline-v1.16-operator-readiness-check-2026-05-10`

## V1.17 branch

- `feature/v1.17-operator-artifact-inventory`

## Exact V1.17 changes

- added offline CLI:
  `lawful-anomaly operator-artifact-inventory`
- gives the operator a deterministic local inventory of run/artifact/export folders before deciding whether outputs are complete, incomplete, safe to retain, or need cleanup
- `--root` points to the workspace directory to inventory (required)
- `--output-dir` controls where report artifacts are written (default: `<root>/.operator-artifact-inventory/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- writes report artifacts under `<output-dir>/`:
  - `operator_artifact_inventory.json`
  - `operator_artifact_inventory.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the generated JSON and Markdown report artifacts
- `SHA256SUMS.txt` never includes its own hash
- stable JSON formatting, stable ordering, no wall-clock timestamp in hashed content
- inventory checks include:
  - **Root summary**: normalized path, existence, directory status, readability
  - **Expected folders**: cache, manifests, artifacts, exports, logs, data
  - **File counts**: JSON, Markdown, SHA256SUMS.txt, ZIP, SQLite, temp/incomplete files
  - **Checksum detection**: lists SHA256SUMS.txt files, parses standard lines, reports malformed lines as warnings, verifies same-directory references <= 25 MB
  - **Safety/export signals**: warns if exact/precise/reviewer-like artifacts appear under public/obfuscated export folders; warns if exports folder exists but no public/obfuscated/reviewer subfolders detected
- result status:
  - `pass` if root exists, no failures, no warnings
  - `warn` if no failures but warnings exist
  - `fail` if root missing, not directory, unreadable, hash mismatch, or missing same-directory checksum target
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not require network
- does not call GitHub
- does not require DB access
- does not mutate source artifact directories
- does not delete or rewrite user files
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior

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

## Validation commands

```
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

- v1.16.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.17 smoke, then tag v1.17.0 and publish GitHub Release if clean
