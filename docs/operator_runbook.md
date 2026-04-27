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
lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted
```

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

## Phase 22 Calibration Registry Snapshot Diff

Compare two verified calibration registry snapshots offline without DB access:

```powershell
lawful-anomaly calibration-label-registry-snapshot-diff --before-snapshot-dir <old_snapshot_dir> --after-snapshot-dir <new_snapshot_dir>
```
