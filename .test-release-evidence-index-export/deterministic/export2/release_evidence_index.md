# Release Evidence Index Export

- Schema version: `v1.12.0`
- Index hash: `2ac638ee035b79879991172cb8cbc129fd1e8efdb60dd8dde3b1d5d81001c92e`
- Evidence root: `.test-release-evidence-index-export/deterministic`
- Evidence dir count: `1`
- Passed count: `1`
- Failed count: `0`
- Checked file count: `2`

## Evidence Directories

- `C:/Dev/Screening_Platform_lab/.test-release-evidence-index-export/deterministic/v1.10.0`: status=`pass` checked=2
  - `full_release_evidence_manifest.json`: sha256_valid=`True`
  - `full_release_evidence_manifest.md`: sha256_valid=`True`

## Exported Artifacts

- `release_evidence_index.json`: sha256=`eb5f58bc5e55bfb8bcb1dfde5726d0afc0cc68c1d050f362c4549397ec17aa0a`
  - Note: self-hash omitted to avoid circular dependency
- `release_evidence_index.md`: sha256=`(see SHA256SUMS.txt)`
  - Note: hash populated after markdown is finalized
- `SHA256SUMS.txt`: sha256=`(see SHA256SUMS.txt)`
  - Note: canonical hash list for all export artifacts

## Notes

- This index was exported offline.
- No network or GitHub API calls were made.
- All evidence directories were verified before export.
- Canonical artifact hashes are available in `SHA256SUMS.txt`.
