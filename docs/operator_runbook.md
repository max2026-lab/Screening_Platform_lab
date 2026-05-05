# Operator Runbook (Installed CLI)

This runbook captures the validated operator flow using the installed `lawful-anomaly` command.

## Preconditions

- Run commands from outside the repository root.
- Do not copy `config/` into your working directory.
- Do not use `PYTHONPATH`.
- Do not use `sitecustomize`.

## Installed Command Flow

Example setup from an outside working directory:

```powershell
# One-time installation examples
uv tool install C:\Dev\Screening_Platform_lab
# or: pip install C:\Dev\Screening_Platform_lab

lawful-anomaly --help
```

Set a DB path and execute the operator flow:

```powershell
$env:LAWFUL_ANOMALY_DB_PATH = "C:\temp\operator.sqlite3"

lawful-anomaly init-db

lawful-anomaly create-run `
  --attestation present `
  --geofence clear `
  --run-id run-001 `
  --aoi-path C:\Dev\Screening_Platform_lab\tests\fixtures\sample_aoi.geojson `
  --start-date 2024-01-01 `
  --end-date 2024-03-31

lawful-anomaly execute-run --run-id run-001
lawful-anomaly review-show --candidate-id <top_candidate_id>

# Inspect run results without re-executing
lawful-anomaly run-summary --run-id run-001

lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted
```

### Zero-Candidate Report Export

For completed or review-ready runs that produced no candidates, a restricted report can still be exported to prove the AOI/date window was screened:

```powershell
lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted
```

This produces a markdown report with:
- `Candidate count: 0`
- A `No Exportable Candidates Found` section
- Run metadata (AOI hash, date window, legal gate decision)
- No exact candidate coordinates

Other audiences will still fail with `no export candidates found for run` when the candidate count is zero.

## Provider Fallback Smoke

Create a temporary endpoints config outside repo root and point `LAWFUL_ANOMALY_ENDPOINTS_PATH` to it.

Minimal fallback config:

```json
{
  "primary": "sim_empty",
  "fallbacks": ["cdse"],
  "sim_empty": {
    "provider": "simulator-empty",
    "role": "primary",
    "synchronous_only": true
  },
  "cdse": {
    "provider": "cdse",
    "role": "fallback",
    "synchronous_only": true
  }
}
```

Run with override:

```powershell
$env:LAWFUL_ANOMALY_ENDPOINTS_PATH = "C:\temp\fallback-endpoints.json"
lawful-anomaly create-run --attestation present --geofence clear --run-id run-001 --aoi-path C:\Dev\Screening_Platform_lab\tests\fixtures\sample_aoi.geojson --start-date 2024-01-01 --end-date 2024-03-31
lawful-anomaly execute-run --run-id run-001
```

Expected `create-run` diagnostics include:

- `fallback_diagnostics.attempted_endpoint_ids`
- `fallback_diagnostics.selected_endpoint_id`
- `fallback_diagnostics.fallback_used`

Expected behavior:

- attempted endpoints include simulator primary and fallback (`sim_empty`, `cdse`)
- selected endpoint is fallback (`cdse`)
- `source_endpoint_id` is fallback (`cdse`) in both `create-run` and `execute-run` outputs

## Cleanup Checks

After smoke execution:

- verify no `config/` was copied into the outside working directory
- verify no `PYTHONPATH` and no `sitecustomize` usage
- run `git status` in repo root and confirm clean working tree

## Repeatable Release Verification

To run the scripted Phase 5 release verification:

```powershell
# from repo root
uv sync
uv pip install -e C:\Dev\Screening_Platform_lab

# release scripts prefer repo-local .venv\Scripts\lawful-anomaly.exe
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase5_release.ps1
```

The script is launched from repo root, but executes operator commands from temporary directories outside the repository.

## Phase 6 Legal Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase6_legal_release.ps1
```

## Phase 7 Composite Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase7_composite_release.ps1
```

## Phase 8 Reproducibility Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase8_reproducibility_release.ps1
```

## Phase 9 Scoring Explainability Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase9_scoring_explainability_release.ps1
```

## Phase 10 Export Audit Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase10_export_audit_release.ps1
```

## Phase 11 Acceptance/KPI Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase11_acceptance_release.ps1
```

## Phase 12 Paid Archive Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase12_paid_archive_release.ps1
```

## Phase 13 Calibration Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase13_calibration_release.ps1
```

## Phase 14 Calibration Policy Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase14_calibration_policy_release.ps1
```

## Phase 15 Calibration Label Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase15_calibration_label_release.ps1
```

## Phase 16 Label Pack Manifest Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase16_label_pack_manifest_release.ps1
```

## Phase 17 Calibration Label Artifact Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase17_calibration_label_artifact_release.ps1
```

## Phase 17 Calibration Label Artifact Export

From an outside working directory with `LAWFUL_ANOMALY_DB_PATH` pointed at the operator database, export a portable label artifact bundle:

```powershell
lawful-anomaly calibration-label-export --run-id <run_id> --output-dir <artifact_dir>
```

## Phase 18 Calibration Label Artifact Verification

Verify a saved calibration label artifact directory later without DB access:

```powershell
lawful-anomaly calibration-label-verify --artifact-dir <artifact_dir>
```

## Phase 19 Calibration Label Artifact Registry

Register a verified artifact bundle into the local registry and list registered bundles:

```powershell
lawful-anomaly calibration-label-register --artifact-dir <artifact_dir>
lawful-anomaly calibration-label-registry-list
```

## Phase 18 Calibration Label Artifact Verify Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase18_calibration_label_artifact_verify_release.ps1
```

## Phase 19 Calibration Artifact Registry Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase19_calibration_artifact_registry_release.ps1
```

## Phase 20 Calibration Registry Snapshot Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase20_calibration_registry_snapshot_release.ps1
```

## Phase 20 Calibration Registry Snapshot Export

Export a portable deterministic snapshot of the entire calibration artifact registry:

```powershell
lawful-anomaly calibration-label-registry-export --output-dir <snapshot_dir>
```

## Phase 21 Calibration Registry Snapshot Verification

Verify a saved calibration registry snapshot directory offline without DB access:

```powershell
lawful-anomaly calibration-label-registry-snapshot-verify --snapshot-dir <snapshot_dir>
```

## Phase 21 Calibration Registry Snapshot Verify Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase21_calibration_registry_snapshot_verify_release.ps1
```

## Phase 22 Calibration Registry Snapshot Diff Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase22_calibration_registry_snapshot_diff_release.ps1
```

## Phase 22 Calibration Registry Snapshot Diff

Compare two verified calibration registry snapshots offline without DB access:

```powershell
lawful-anomaly calibration-label-registry-snapshot-diff --before-snapshot-dir <old_snapshot_dir> --after-snapshot-dir <new_snapshot_dir>
```

## Phase 23 Calibration Registry Snapshot Diff Export Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase23_calibration_registry_snapshot_diff_export_release.ps1
```

## Phase 23 Calibration Registry Snapshot Diff Export

Export a deterministic offline diff evidence pack of two verified calibration registry snapshots:

```powershell
lawful-anomaly calibration-label-registry-snapshot-diff-export --before-snapshot-dir <old_snapshot_dir> --after-snapshot-dir <new_snapshot_dir> --output-dir <diff_evidence_dir>
```

## Phase 24 Calibration Registry Snapshot Diff Export Verification

Verify a saved calibration registry snapshot diff evidence pack offline without DB access:

```powershell
lawful-anomaly calibration-label-registry-snapshot-diff-export-verify --evidence-dir <diff_evidence_dir>
```

## Phase 24 Calibration Registry Snapshot Diff Export Verify Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase24_calibration_registry_snapshot_diff_export_verify_release.ps1
```

## Phase 25 Calibration Registry Snapshot Diff Acceptance

Apply deterministic acceptance policy to a verified registry diff evidence pack offline without DB access:

```powershell
lawful-anomaly calibration-label-registry-snapshot-diff-export-accept --evidence-dir <diff_evidence_dir>
```

## Phase 25 Calibration Registry Diff Acceptance Gate Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase25_calibration_registry_diff_acceptance_gate_release.ps1
```

## Phase 26 Calibration Sign-off Evidence Export

Export a durable calibration sign-off evidence bundle from a verified and accepted diff evidence pack:

```powershell
lawful-anomaly calibration-signoff-evidence-export --evidence-dir <diff_evidence_dir> --output-dir <signoff_evidence_dir>
```

## Phase 26 Calibration Sign-off Evidence Bundle Release Verification

From repo root, run `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` first.
The release scripts prefer repo-local `.venv\Scripts\lawful-anomaly.exe`.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase26_calibration_signoff_evidence_bundle_release.ps1
```

## Phase 27 Full Release Verification Chain

Run the complete validated test and release suite through Phase 26. This is the required full pre-tag validation chain after Phase 26.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase27_full_release_verification_chain.ps1
```

## Phase 28 Full Release Evidence Manifest

Run the Phase 27 full chain and write a durable local evidence manifest.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_phase28_full_release_evidence_manifest.ps1
```

## V1 Release Candidate

The V1 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_RELEASE_NOTES.md`.

Validate the release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## V1.1 No-Candidates Export Report Release Verification

Run the V1.1 release verification script to confirm zero-candidate export report behavior:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

This script verifies:
- Known-candidate export still works for `report_pdf restricted`
- Zero-candidate runs produce a restricted markdown report instead of failing
- Unsupported audiences (e.g., `public`) still fail for zero-candidate runs
- Repo cleanliness and token-free remotes after verification

## V1.1 Operator Manual

For the practical target-area-to-export workflow, including zero-candidate exports, see:
`docs/V1_1_OPERATOR_MANUAL_TARGET_TO_EXPORT.md`

## V1.1 Release Candidate

The V1.1 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_1_RELEASE_NOTES.md`.

Validate the V1.1 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

Validate the full release chain (through Phase 28) with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## V1.2 Release Candidate

The V1.2 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_2_RELEASE_NOTES.md`.

Validate the V1.2 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
```

Validate the V1.1 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

Validate the full release chain (through Phase 28) with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## V1.3 Real STAC Provider Smoke

For the metadata-only real STAC provider smoke path, configuration, and live operator workflow, see:
`docs/V1_3_REAL_STAC_PROVIDER_SMOKE.md`

## V1.3 Release Candidate

The V1.3 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_3_RELEASE_NOTES.md`.

Validate the V1.3 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
```

Validate the V1.2 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
```

Validate the V1.1 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

Validate the full release chain (through Phase 28) with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```

## V1.3 Real STAC Provider Smoke

For the metadata-only real STAC provider smoke path, configuration, and live operator workflow, see:
`docs/V1_3_REAL_STAC_PROVIDER_SMOKE.md`

## V1.4 Real AOI Bbox in STAC Smoke

V1.4 wires the real AOI GeoJSON bbox into the STAC metadata-only `/search` payload when the endpoint is explicitly active.

- Normal tests remain mocked/offline
- Live smoke still requires network and explicit active endpoint config
- No raster download
- No scoring/calibration/DB schema changes

## V1.4 Real STAC AOI Bbox Release Verification

Run the V1.4 release verification script to confirm AOI bbox wiring into STAC smoke without network:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
```

This script verifies:
- AOI bbox extraction and coordinate validation tests pass
- Mocked STAC provider tests include bbox in POST payload
- Active real STAC fails clearly when no AOI bbox is provided
- Docs state V1.4 wires real AOI bbox into STAC `/search`
- Default endpoints config keeps `earth_search` inactive
- `metadata_only` is true in config
- No raster download behavior in source
- Repo cleanliness and token-free remotes after verification

## V1.3 Real STAC Provider Smoke Release Verification

Run the V1.3 release verification script to confirm mocked STAC provider behavior without network:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
```

This script verifies:
- Mocked STAC provider tests pass without internet
- Default endpoints config keeps `earth_search` inactive
- `metadata_only` is true in config
- No raster download behavior in source
- Docs state metadata-only, offline tests, and network-required live smoke

## V1.2 Run Summary Release Verification

Run the V1.2 release verification script to confirm run-summary behavior for both candidate-backed and zero-candidate runs:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_2_run_summary_release.ps1
```

This script verifies:
- Candidate-backed runs produce run-summary with `candidate_count > 0` and `top_candidate_id` present
- Zero-candidate runs produce run-summary with `candidate_count = 0` and `top_candidate_id` null
- Export fields (`latest_export_record_id`, `latest_export_artifact_path`) appear after `export-create`
- Missing run IDs return non-zero exit with `run not found` stderr
- Repo cleanliness and token-free remotes after verification

## V1.5 Live Real STAC Metadata Smoke

V1.5 adds a network-required live STAC metadata-only smoke script. This is **not** part of normal offline pytest or release verification.

```powershell
$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\smoke_live_v1_5_real_stac_metadata.ps1
```

What it does:
- Queries the real Earth Search STAC `/search` endpoint for metadata only
- Uses a real AOI GeoJSON bbox in the STAC POST payload
- Uses RFC3339 datetime interval in the STAC POST payload
- Verifies `discovered_scenes` and `source_scene_manifest_hash` are persisted
- Verifies no raster assets are downloaded

Requirements:
- Network connectivity to `https://earth-search.aws.element84.com/v1`
- Explicit opt-in via `$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"`

For full details, see `docs/V1_5_LIVE_STAC_METADATA_SMOKE.md`.

## V1.5 Live STAC Metadata Release Verification

Run the V1.5 release verification script to confirm the live smoke script guard, contract, and RFC3339 datetime fix without network:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_5_live_stac_metadata_release.ps1
```

This script verifies:
- Offline mocked STAC/AOI tests pass
- Live smoke script exists with explicit opt-in guard
- Live smoke script refuses to run without `$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"`
- Live smoke script uses Earth Search, `metadata_only`, `sentinel-2-l2a`
- Live smoke script checks RFC3339 datetime, bbox, discovered_scenes, no raster download
- Docs state live/network-required, metadata-only, no raster download
- RFC3339 `_build_stac_datetime_interval` is present in `stac_client.py`
- Default endpoints config keeps `earth_search` inactive
- Repo cleanliness and token-free remotes after verification

This script is **offline by default** and does not call real Earth Search. Live smoke remains explicit manual/operator validation only.

## V1.6 Export Bundle Release Verification

Run the V1.6 release verification script to confirm report export ZIP bundles are created correctly:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_6_export_bundle_release.ps1
```

This script verifies:
- Offline export repository tests pass
- `export_repository.py` contains bundle implementation (`bundle_path`, `_write_report_bundle`, `audit_manifest.json`, `SHA256SUMS.txt`, `zipfile`)
- Tests assert bundle creation for report exports
- Tests assert zero-candidate bundles and non-report audiences skip bundles
- CLI `export-create` for `report_pdf` produces `bundle_path` ending in `.zip`
- ZIP contains exactly: markdown report, `audit_manifest.json`, `SHA256SUMS.txt`
- `audit_manifest.json` inside ZIP matches output `audit_manifest`
- `SHA256SUMS.txt` validates report and audit manifest hashes
- Restricted reports do not leak exact coordinates
- Zero-candidate restricted reports still create bundles
- Repo cleanliness and token-free remotes after verification

This script is **offline** and does not require network.

## V1.6 Release Candidate

The V1.6 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_6_RELEASE_NOTES.md`.

Validate the V1.6 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_6_export_bundle_release.ps1
```

This verification is offline and validates report ZIP bundles, `audit_manifest.json`, and `SHA256SUMS.txt`. No DB schema, scoring, or provider changes.

## V1.5 Release Candidate

The V1.5 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_5_RELEASE_NOTES.md`.

Validate the V1.5 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_5_live_stac_metadata_release.ps1
```

Manual live smoke (network-required, opt-in only):

```powershell
$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"
powershell -ExecutionPolicy Bypass -File scripts\smoke_live_v1_5_real_stac_metadata.ps1
```

## V1.4 Release Candidate

The V1.4 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_4_RELEASE_NOTES.md`.

Validate the V1.4 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_4_real_stac_aoi_bbox_smoke_release.ps1
```

Validate the V1.3 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_3_real_stac_provider_smoke_release.ps1
```

Validate the V1.2 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_2_run_summary_release.ps1
```

Validate the V1.1 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

Validate the full release chain (through Phase 28) with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite
```
