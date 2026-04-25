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
