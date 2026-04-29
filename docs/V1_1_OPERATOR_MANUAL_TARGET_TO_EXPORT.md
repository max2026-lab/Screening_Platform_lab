# V1.1 Operator Manual: Target-Area-to-Export Workflow

This manual covers the practical operator flow from AOI selection through candidate export, including the V1.1 zero-candidate report path.

## Prerequisites

- Repository cloned at `C:\Dev\Screening_Platform_lab`
- `uv sync` and `uv pip install -e C:\Dev\Screening_Platform_lab` completed
- Working from a directory **outside** the repo root for all operator commands

## Install / Select Current Repo State

```powershell
# From repo root (do this once per session if needed)
cd C:\Dev\Screening_Platform_lab
uv sync
uv pip install -e C:\Dev\Screening_Platform_lab
```

## Workspace Setup Outside Repo Root

```powershell
# Create an operator workspace
$workspace = "C:\temp\operator-runs"
New-Item -ItemType Directory -Path $workspace -Force | Out-Null
cd $workspace
```

## Set Database Path

```powershell
$env:LAWFUL_ANOMALY_DB_PATH = "$workspace\operator.sqlite3"
```

## Write AOI GeoJSON (UTF-8 No BOM)

Use .NET UTF8Encoding to avoid BOM, which can cause JSON parse errors:

```powershell
$aoiPath = "$workspace\aoi.geojson"
$json = @'
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [30.0, 10.0],
            [40.0, 10.0],
            [40.0, 20.0],
            [30.0, 20.0],
            [30.0, 10.0]
          ]
        ]
      }
    }
  ]
}
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($aoiPath, $json, $utf8NoBom)
```

## Initialize Database

```powershell
lawful-anomaly init-db
```

## Create Run

```powershell
lawful-anomaly create-run `
  --attestation present `
  --geofence clear `
  --run-id run-001 `
  --aoi-path $aoiPath `
  --start-date 2024-01-01 `
  --end-date 2024-03-31
```

## Execute Run

```powershell
lawful-anomaly execute-run --run-id run-001
```

## Run Summary

Inspect run results without re-executing:

```powershell
lawful-anomaly run-summary --run-id run-001
```

This returns a JSON summary with:
- `run_id`
- `status`
- `candidate_count`
- `top_candidate_id` (null if zero candidates)
- `tile_count` and `selected_tile_count`
- `latest_export_record_id` and `latest_export_artifact_path` (null if no export)
- AOI hash, date window, legal gate decision, source endpoint, source scene manifest hash

The `run-summary` command reads persisted data only and does not execute provider or network behavior. Use it as the recommended inspection step after `execute-run` to check `candidate_count`.

## Candidate Count > 0 Path

When candidates exist, review and export normally:

```powershell
# List review queue
lawful-anomaly review-queue --run-id run-001

# Inspect a candidate
lawful-anomaly review-show --candidate-id <candidate_id>

# Optionally decide
lawful-anomaly review-decide `
  --candidate-id <candidate_id> `
  --run-id run-001 `
  --reviewer-id operator-1 `
  --decision approved

# Export restricted report
lawful-anomaly export-create `
  --run-id run-001 `
  --audience report_pdf `
  --requested-precision restricted

# Open the report (path is in the JSON output)
```

The report will contain:
- `Candidate count: <N>` where N > 0
- A `## Candidate Summary` table
- No exact coordinates (restricted precision)

## Candidate Count = 0 Path (V1.1)

In V1.0.0, zero-candidate runs failed with:
```
no export candidates found for run: <run_id>
```

In V1.1, for completed/review_ready runs with zero candidates:

```powershell
lawful-anomaly export-create `
  --run-id run-001 `
  --audience report_pdf `
  --requested-precision restricted
```

This now succeeds and produces a restricted markdown report containing:
- `Candidate count: 0`
- `## No Exportable Candidates Found`
- `This AOI/date window was screened and produced zero exportable candidates.`
- Legal gate decision
- Date window (start and end dates)
- No exact candidate coordinates

The export JSON still includes:
- `export_record_id`
- `candidates: []`
- `audit_manifest`
- `exact_coordinates_included: false`

### Unsupported Zero-Candidate Audiences Still Fail

```powershell
lawful-anomaly export-create --run-id run-001 --audience public
```

Still returns:
```
no export candidates found for run: run-001
```

## Troubleshooting

### UTF-8 BOM AOI Error

**Symptom:** `json.JSONDecodeError` or `UnicodeDecodeError` during `create-run`.

**Fix:** Use .NET `UTF8Encoding($false)` instead of `Set-Content -Encoding UTF8`:
```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($aoiPath, $json, $utf8NoBom)
```

### Run Not Found

**Symptom:** `run not found: <run_id>`

**Causes:**
- Wrong `LAWFUL_ANOMALY_DB_PATH`
- Run was created in a different DB file
- Typo in `run_id`

**Fix:** Check the DB path and list available runs via the review queue or database inspection.

### Old V1 No Export Candidates Behavior

**Symptom:** `no export candidates found for run: <run_id>` on a zero-candidate run.

**Check:**
1. Is the run status `completed` or `review_ready`? Only these statuses allow zero-candidate export.
2. Is the audience `report_pdf` with `--requested-precision restricted`? Only this combination is supported.
3. Is the CLI from the V1.1 codebase? `uv pip install -e C:\Dev\Screening_Platform_lab` to refresh.

### Restricted Report Shows [0.0, 0.0] Coordinates

**Symptom:** Candidate table shows centroids like `[0.0, 0.0]`.

**Explanation:** For very small AOIs, the restricted precision snap can collapse coordinates to the origin. This is expected behavior for the restricted precision tier. Use `reviewer` or `field` audience if exact coordinates are required and legally allowed.

## Validation

Run the full V1.1 release verification:

```powershell
# From repo root
cd C:\Dev\Screening_Platform_lab
powershell -ExecutionPolicy Bypass -File scripts\verify_v1_1_no_candidates_export_report_release.ps1
```

This script verifies:
- Known-candidate export still works
- Zero-candidate report export succeeds
- Unsupported public zero-candidate export still fails
- Repo cleanliness after verification
