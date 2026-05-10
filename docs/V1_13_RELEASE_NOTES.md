# V1.13 Release Notes — Release Evidence Index Export Verifier

## Inherited release

- v1.12.0

## Base commit

- `6576f7ee62c9b3931cc288c3b832ffcb8348b496`

## Baseline tag

- `baseline-v1.12-release-evidence-index-export-2026-05-10`

## V1.13 branch

- `feature/v1.13-release-evidence-index-export-verify`

## Exact V1.13 changes

- added offline CLI:
  `lawful-anomaly release-evidence-index-export-verify`
- verifies artifacts produced by V1.12 `release-evidence-index-export`
- validates `SHA256SUMS.txt` exists and hashes all produced artifacts
- validates `SHA256SUMS.txt` does not include itself
- supports all V1.12 output formats: `json`, `markdown`, `both`
- if JSON exists:
  - requires `schema.version == v1.12.0`
  - requires `index_hash`
  - requires `evidence_directories` list
  - requires `export_artifacts` list
  - requires `release_evidence_index.json` self-hash is null with self-reference note
  - cross-checks markdown hash against `SHA256SUMS.txt` when markdown exists
- if Markdown exists:
  - requires `# Release Evidence Index Export` heading
  - requires Index hash line
  - requires `## Evidence Directories` section
  - requires `## Exported Artifacts` section
- returns exit code 0 only when verification passes
- returns nonzero for missing files, hash mismatches, malformed JSON, malformed markdown, malformed SHA256SUMS, or unsupported artifact entries
- prints deterministic JSON result by default
- does not require DB access
- does not require network
- does not call GitHub
- does not modify V1.12 exporter behavior

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

## Validation commands

```
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

- v1.12.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.13 smoke, then tag v1.13.0 and publish GitHub Release if clean
