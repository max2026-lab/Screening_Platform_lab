# Release Evidence Index Export

- Schema version: `v1.12.0`
- Index hash: `0e3c7472292ca75971f735356304f951ffd2c9f6492370d0b0e13a61f9614011`
- Evidence root: `.test-release-evidence-index-export/root_pass`
- Evidence dir count: `2`
- Passed count: `2`
- Failed count: `0`
- Checked file count: `4`

## Evidence Directories

- `C:/Dev/Screening_Platform_lab/.test-release-evidence-index-export/root_pass/v1.10.0`: status=`pass` checked=2
  - `full_release_evidence_manifest.json`: sha256_valid=`True`
  - `full_release_evidence_manifest.md`: sha256_valid=`True`
- `C:/Dev/Screening_Platform_lab/.test-release-evidence-index-export/root_pass/v1.11.0`: status=`pass` checked=2
  - `full_release_evidence_manifest.json`: sha256_valid=`True`
  - `full_release_evidence_manifest.md`: sha256_valid=`True`

## Exported Artifacts

- `release_evidence_index.json`: sha256=`9990814edfac03687f20de88d36b593dd25d5f4a70e49f4511e8b1d4e6c74556`
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
