# Release Evidence Index Export

- Schema version: `v1.12.0`
- Index hash: `4456d67447013fea732a432937a48131b41801b6e377b8e10acf048016422449`
- Evidence list: `.test-release-evidence-index-export\list_mode\evidence-list.txt`
- Evidence dir count: `2`
- Passed count: `2`
- Failed count: `0`
- Checked file count: `4`

## Evidence Directories

- `C:/Dev/Screening_Platform_lab/.test-release-evidence-index-export/list_mode/evidence1`: status=`pass` checked=2
  - `full_release_evidence_manifest.json`: sha256_valid=`True`
  - `full_release_evidence_manifest.md`: sha256_valid=`True`
- `C:/Dev/Screening_Platform_lab/.test-release-evidence-index-export/list_mode/evidence2`: status=`pass` checked=2
  - `full_release_evidence_manifest.json`: sha256_valid=`True`
  - `full_release_evidence_manifest.md`: sha256_valid=`True`

## Exported Artifacts

- `release_evidence_index.json`: sha256=`a62ed8c2df657c90efaad93a24cc3361945b1618df4a27d7d40e26a8c33ec0df`
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
