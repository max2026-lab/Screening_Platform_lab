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

## V1.7 Report Bundle Manifest Release Verification

Run the V1.7 release verification script to confirm report export sidecar manifest JSON is created correctly:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Dev\Screening_Platform_lab\scripts\verify_v1_7_report_bundle_manifest_release.ps1
```

This script verifies:
- Offline export repository tests pass
- `export_repository.py` contains sidecar manifest implementation (`bundle_manifest_path`, `_write_report_bundle_manifest`, `v1.7_report_bundle_manifest`, `bundle_sha256`, `bundle_members`, `files`)
- Tests assert sidecar manifest creation for report exports
- Tests assert zero-candidate sidecars and non-report audiences skip sidecars
- CLI `export-create` for `report_pdf` produces `bundle_manifest_path` ending in `.manifest.json`
- Sidecar manifest contains `schema_version`, `bundle_sha256`, `bundle_members`, `files` with SHA256 hashes
- Sidecar manifest does not leak `centroid`, `clipped_geometry`, `bounds`, or `coordinates`
- Repo cleanliness and token-free remotes after verification

This script is **offline** and does not require network.

## V1.8 Operator Export Bundle Verification CLI

V1.8 adds an offline operator CLI command that verifies an existing report ZIP bundle and V1.7 sidecar manifest from disk without DB access and without rerunning exports.

```powershell
lawful-anomaly export-bundle-verify --bundle-manifest-path exports/reports/<bundle>.zip.manifest.json --export-root .
```

State:
- offline
- no DB required
- no network required
- verifies ZIP bundle and V1.7 sidecar manifest from disk
- validates `bundle_sha256`, `bundle_members`, `SHA256SUMS.txt`, `audit_manifest.json`, and sidecar files hashes
- checks no `centroid`/geometry leakage in sidecar
- does not rerun `export-create`
- does not change DB/schema/scoring/provider behavior

## V1.9 Operator Export Bundle Batch Verification CLI

V1.9 adds an offline batch CLI command that verifies all report ZIP bundles and V1.7 sidecar manifests in a folder or from an explicit manifest list.

```powershell
lawful-anomaly export-bundle-verify-batch --reports-dir exports/reports --export-root .
lawful-anomaly export-bundle-verify-batch --manifest-list manifest-list.txt --export-root .
```

State:
- offline
- no DB required for verification
- no network required
- verifies all report ZIP bundles and V1.7 sidecar manifests from disk
- reuses V1.8 single-bundle verification logic
- validates `bundle_sha256`, `bundle_members`, `SHA256SUMS.txt`, `audit_manifest.json`, and sidecar files hashes for every bundle
- supports JSON and markdown output
- supports `--fail-fast`
- does not rerun `export-create`
- does not change DB/schema/scoring/provider behavior

## V1.10 Operator Release Evidence Verification CLI

V1.10 adds an offline CLI command that verifies downloaded GitHub Release evidence artifacts from disk.

```powershell
lawful-anomaly release-evidence-verify --evidence-dir .release-evidence/phase28-full-release-evidence-manifest
```

State:
- offline
- no DB required
- no network required
- verifies downloaded GitHub Release evidence artifacts from disk
- validates `full_release_evidence_manifest.json` parses
- validates `full_release_evidence_manifest.md` is recognizable release evidence markdown
- validates `SHA256SUMS.txt` hashes for json and markdown evidence files
- does not call GitHub
- does not rerun Phase 28
- does not change DB/schema/scoring/provider behavior

## V1.11 Operator Release Evidence Index Verification CLI

V1.11 adds an offline CLI command that verifies multiple downloaded GitHub Release evidence directories from disk in one command.

```powershell
lawful-anomaly release-evidence-index-verify --evidence-root downloaded-releases
lawful-anomaly release-evidence-index-verify --evidence-list evidence-list.txt
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not rerun Phase 28
- recursively discovers release evidence directories by required files
- verifies every evidence directory using V1.10 single evidence verifier
- supports JSON and markdown output
- supports fail-fast
- produces deterministic index_hash
- detects duplicate evidence-list paths
- does not change DB/schema/scoring/provider behavior

## V1.12 Operator Release Evidence Index Export CLI

V1.12 adds an offline CLI command that verifies and exports a release evidence index to deterministic artifacts.

```powershell
lawful-anomaly release-evidence-index-export --evidence-root downloaded-releases
lawful-anomaly release-evidence-index-export --evidence-root downloaded-releases --format both
lawful-anomaly release-evidence-index-export --evidence-list evidence-list.txt --output-dir ./export
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not rerun Phase 28
- reuses V1.11 release evidence index verifier logic
- verifies all evidence directories before producing artifacts
- fails nonzero without producing artifacts if verification fails
- produces deterministic `release_evidence_index.json`, `release_evidence_index.md`, and `SHA256SUMS.txt` when format is `both`
- `--format json` produces only `release_evidence_index.json` and `SHA256SUMS.txt`
- `--format markdown` produces only `release_evidence_index.md` and `SHA256SUMS.txt`
- `SHA256SUMS.txt` lists only the artifacts produced for the selected format and never includes its own hash
- JSON includes schema/version field for V1.12, index_hash, and per-directory status
- markdown summarizes the index in operator-readable form
- default format: both
- does not change DB/schema/scoring/provider behavior

## V1.13 Release Evidence Index Export Verifier

V1.13 adds an offline CLI command that verifies artifacts produced by V1.12 `release-evidence-index-export`.

```powershell
lawful-anomaly release-evidence-index-export-verify --export-dir ./export
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- validates `SHA256SUMS.txt` exists and hashes all produced artifacts
- validates `SHA256SUMS.txt` does not include itself
- supports all V1.12 output formats (`json`, `markdown`, `both`)
- if JSON exists: requires `schema.version == v1.12.0`, `index_hash`, `evidence_directories`, `export_artifacts`, and null self-hash with self-reference note
- if Markdown exists: requires heading, index hash line, Evidence Directories section, and Exported Artifacts section
- cross-checks markdown hash in JSON against `SHA256SUMS.txt`
- returns exit code 0 only when verification passes
- does not modify V1.12 exporter behavior
- does not change DB/schema/scoring/provider behavior

## V1.14 Release Evidence Index Export Round-Trip Smoke

V1.14 adds an offline CLI command that performs a complete local round-trip smoke of the V1.12 exporter and V1.13 verifier.

```powershell
lawful-anomaly release-evidence-index-export-smoke --evidence-root ./evidence --output-root ./smoke
lawful-anomaly release-evidence-index-export-smoke --evidence-root ./evidence --output-root ./smoke --format json
lawful-anomaly release-evidence-index-export-smoke --evidence-root ./evidence --output-root ./smoke --format all
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not mutate source evidence directories
- reuses existing V1.12 exporter and V1.13 verifier
- `--format all` runs `json`, `markdown`, and `both`
- default format: `all`
- deterministic output directories:
  - `<output-root>/release-evidence-index-export-smoke/json`
  - `<output-root>/release-evidence-index-export-smoke/markdown`
  - `<output-root>/release-evidence-index-export-smoke/both`
- exits nonzero if any format fails export or verify
- prints deterministic JSON result with `schema.version == v1.14.0`
- result includes per-format export status, verify status, artifact names/hashes, and overall status
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not change DB/schema/scoring/provider behavior

## V1.15 Release Evidence Export Smoke Report

V1.15 adds an offline CLI command that runs the V1.14 round-trip smoke and writes durable evidence report artifacts.

```powershell
lawful-anomaly release-evidence-index-export-smoke-report --evidence-root ./evidence --output-root ./report
lawful-anomaly release-evidence-index-export-smoke-report --evidence-root ./evidence --output-root ./report --format json
lawful-anomaly release-evidence-index-export-smoke-report --evidence-root ./evidence --output-root ./report --format all
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not mutate source evidence directories
- reuses existing V1.14 smoke implementation
- `--output-root` is required
- `--format all` runs `json`, `markdown`, and `both`
- default format: `all`
- fails deterministically if `output_root` is the same as or inside `evidence_root`
- report artifacts are written under `<output-root>/release-evidence-index-export-smoke-report/`:
  - `release_evidence_index_export_smoke_report.json`
  - `release_evidence_index_export_smoke_report.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the JSON and Markdown report artifacts and never includes its own hash
- JSON report includes `schema.version == v1.15.0`, embedded V1.14 smoke result, per-format status, artifact names/hashes, and overall status
- Markdown report summarizes the same result in operator-readable form
- if smoke fails, report artifacts are still written describing the failure, then exits nonzero
- no timestamps in hashed or report content
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not change DB/schema/scoring/provider behavior

## V1.16 Operator Readiness Check

V1.16 adds an offline operator readiness CLI command that produces a deterministic local readiness report before attempting real screening/review work.

```powershell
lawful-anomaly operator-readiness-check
lawful-anomaly operator-readiness-check --output-dir ./readiness
lawful-anomaly operator-readiness-check --format json
lawful-anomaly operator-readiness-check --format both
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not require paid provider credentials
- does not mutate database or source data
- does not start workers
- does not run STAC/live provider smoke
- `--output-dir` controls where report artifacts are written (default: `.operator-readiness/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- report artifacts:
  - `operator_readiness_check.json`
  - `operator_readiness_check.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the JSON and Markdown report artifacts and never includes its own hash
- checks include runtime, git context, config/environment presence, filesystem readiness, safety config, and database status
- safety config rejects `EXPORT_UNCONFIRMED_COORDINATE_MODE=exact`, warns on non-default grid km, warns if UP42 is explicitly enabled
- database/Redis reports `not_checked` as a warning without adding broad new infrastructure
- result status semantics:
  - `pass` only if required checks pass and there are no warnings
  - `warn` if required checks pass but optional/not_checked warnings exist
  - `fail` if required safety settings are unsafe or required storage paths are missing/not writable
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not modify release evidence commands
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not change DB/schema/scoring/provider behavior

## V1.17 Operator Artifact Inventory

V1.17 adds an offline operator artifact inventory CLI command that produces a deterministic local inventory of run/artifact/export folders.

```powershell
lawful-anomaly operator-artifact-inventory --root ./workspace
lawful-anomaly operator-artifact-inventory --root ./workspace --output-dir ./inventory
lawful-anomaly operator-artifact-inventory --root ./workspace --format json
lawful-anomaly operator-artifact-inventory --root ./workspace --format both
```

State:
- offline
- no DB required
- no network required
- does not call GitHub
- does not require paid provider credentials
- does not mutate source artifact directories
- does not delete or rewrite user files
- `--root` is required and points to the workspace directory to inventory
- `--output-dir` controls where report artifacts are written (default: `<root>/.operator-artifact-inventory/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- report artifacts:
  - `operator_artifact_inventory.json`
  - `operator_artifact_inventory.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the JSON and Markdown report artifacts and never includes its own hash
- checks include root summary, expected folder presence, file counts, SHA256SUMS detection/verification, and export safety signals
- warns if exact/precise/reviewer-like artifacts appear under public/obfuscated export folders
- warns if exports folder exists but no public/obfuscated/reviewer subfolders detected
- verifies same-directory checksum references up to 25 MB
- result status:
  - `pass` if root exists, no failures, no warnings
  - `warn` if no failures but warnings exist
  - `fail` if root missing, not directory, unreadable, hash mismatch, or missing same-directory checksum target
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior
- does not change DB/schema/scoring/provider behavior

## V1.18 Review Package Readiness Check

V1.18 adds an offline review package readiness check CLI command that produces a deterministic readiness report before exposing a screening run to analyst review.

```powershell
lawful-anomaly review-package-readiness-check --run-id <run_id>
lawful-anomaly review-package-readiness-check --run-id <run_id> --artifact-root ./artifacts
lawful-anomaly review-package-readiness-check --run-id <run_id> --format json
lawful-anomaly review-package-readiness-check --run-id <run_id> --format both
```

State:
- offline
- no network required
- does not call GitHub
- does not require provider calls
- does not mutate database
- does not start workers
- does not build or rewrite review packages
- `--run-id` is required
- `--artifact-root` is optional; if provided, artifact files are inspected read-only
- `--output-dir` controls where report artifacts are written (default: `.review-package-readiness/`)
- `--format` supports `json`, `markdown`, `both` (default: `both`)
- report artifacts:
  - `review_package_readiness_check.json`
  - `review_package_readiness_check.md`
  - `SHA256SUMS.txt`
- `SHA256SUMS.txt` hashes only the JSON and Markdown report artifacts and never includes its own hash
- checks include run metadata, legal/safety gate, candidate/review queue readiness, candidate score/duplicate checks, and optional artifact root scanning
- fails if legal gate decision is not `pass`
- fails if run is completed/review_ready but has neither candidates nor an allowed zero-candidate export path
- warns if candidates exist but review queue is empty
- warns if score or score breakdown is missing for candidates
- warns if possible_duplicate flags are true
- warns on geofence hits
- warns on incomplete/temp artifacts when `--artifact-root` is provided
- warns if public/obfuscated files contain exact/precise/reviewer_only in filename
- result status:
  - `pass` if required checks pass and there are no warnings
  - `warn` if required checks pass but warnings exist
  - `fail` if run missing, legal gate blocks review, artifact-root missing/not directory, or required review-readiness invariants fail
- exit code 0 for `pass` and `warn`; nonzero for `fail`
- does not modify release evidence commands
- does not modify operator-readiness behavior
- does not modify operator-artifact-inventory behavior
- does not modify V1.12 exporter behavior
- does not modify V1.13 verifier behavior
- does not modify V1.14 smoke behavior
- does not modify V1.15 smoke report behavior
- does not modify V1.16 operator readiness behavior
- does not modify V1.17 operator artifact inventory behavior
- does not change DB/schema/scoring/provider behavior

## V1.10 Release Candidate

The V1.10 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_10_RELEASE_NOTES.md`.

Validate the V1.10 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_10_release_evidence_verifier_release.ps1
```

## V1.9 Release Candidate

The V1.9 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_9_RELEASE_NOTES.md`.

Validate the V1.9 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_9_export_bundle_verify_batch_release.ps1
```

Validate the V1.8 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_8_export_bundle_verify_cli_release.ps1
```

Validate the V1.7 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_7_report_bundle_manifest_release.ps1
```

## V1.7 Release Candidate

The V1.7 release candidate scope, release gate, limitations, rollback point, and next step are locked in `docs/V1_7_RELEASE_NOTES.md`.

Validate the V1.7 release candidate from repo root with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_7_report_bundle_manifest_release.ps1
```

This verification is offline and validates report bundle sidecar manifest JSON, `bundle_sha256`, `bundle_members`, and `files` hashes. It also verifies no `centroid`/geometry leakage. No DB schema, scoring, or provider changes.

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
