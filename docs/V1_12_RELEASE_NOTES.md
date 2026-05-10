# V1.12 Release Notes — Release Evidence Index Export

## Inherited release

- v1.11.0

## Base commit

- `16af7d98552befe7b4fb7c4495c3573f59d4dce3`

## Baseline tag

- `baseline-v1.11-release-evidence-index-verifier-2026-05-10`

## V1.12 branch

- `feature/v1.12-release-evidence-index-export`

## Exact V1.12 changes

- added offline CLI:
  `lawful-anomaly release-evidence-index-export`
- verifies and exports a release evidence index to deterministic artifacts
- reuses V1.11 `release-evidence-index-verify` logic
- verifies all evidence directories before producing artifacts
- fails nonzero without producing artifacts if verification fails
- produces deterministic `release_evidence_index.json`
- produces deterministic `release_evidence_index.md`
- produces deterministic `SHA256SUMS.txt`
- JSON includes schema/version field for V1.12
- JSON includes index_hash from verifier logic
- JSON includes evidence_root, evidence_list, per-directory status, file hashes
- markdown summarizes the same index in operator-readable form
- supports `--evidence-root`
- supports `--evidence-list`
- supports `--output-dir`
- supports `--format json|markdown|both`
- default format: both
- does not require DB access
- does not require network
- does not call GitHub
- does not rerun Phase 28

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

## Validation commands

```
uv run pytest tests/integration/test_release_evidence_index_export_cli.py
uv run pytest tests/integration/test_release_evidence_index_verify_cli.py
uv run pytest tests/integration/test_release_evidence_verify_cli.py
uv run pytest tests/integration/test_export_bundle_verify_batch_cli.py
uv run pytest tests/integration/test_export_bundle_verify_cli.py
uv run pytest tests/integration/test_export_repository.py
uv run pytest
```

## Release gate

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

- v1.11.0

## Next step

- after branch validation, merge to main, tag baseline, run clean-machine V1.12 smoke, then tag v1.12.0 and publish GitHub Release if clean
