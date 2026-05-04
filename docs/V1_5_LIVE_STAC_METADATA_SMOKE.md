# V1.5 Live Real STAC Metadata Smoke

This document describes the live, network-required real STAC metadata-only smoke path added in V1.5.

## What It Is

A script that performs a real Earth Search STAC `/search` metadata-only query using a real AOI bbox and RFC3339 datetime interval, then verifies that `discovered_scenes` and `source_scene_manifest_hash` were persisted correctly.

## What It Is Not

- It does not download raster assets
- It does not run scoring, candidate generation, or calibration
- It does not change the DB schema
- It does not make real provider behavior the default for normal offline runs
- It is not part of normal pytest or release verification (those remain offline)

## Prerequisites

- Network connectivity to `https://earth-search.aws.element84.com/v1`
- Explicit opt-in via environment variable

## Operator Workflow

Set the opt-in flag and run the smoke script from repo root:

```powershell
$env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE = "1"
powershell -ExecutionPolicy Bypass -File scripts\smoke_live_v1_5_real_stac_metadata.ps1
```

## What the Script Does

1. Validates repo-local `lawful-anomaly` CLI exists
2. Creates a temporary working directory outside the repo
3. Writes a small AOI GeoJSON file with a valid bbox
4. Creates a temporary active endpoint config for Earth Search
5. Runs `init-db` and `create-run` with the live endpoint
6. Verifies:
   - `create-run` exits 0
   - `run_id` is correct
   - `source_endpoint_id` is `earth_search`
   - `source_scene_manifest_hash` exists
   - Manifest file exists and contains `query_parameters.bbox`
   - Manifest `query_parameters.datetime` is an RFC3339 interval (not `YYYY-MM-DD/YYYY-MM-DD`)
   - Manifest collections include `sentinel-2-l2a`
   - Scenes have `scene_id`, `acquired_at`, `provider_item_id`, and `collection`
   - `discovered_scenes` rows were written to the DB
   - `source_scene_manifests` row exists in the DB
   - No raster files were downloaded into the temp directory
7. Verifies repo cleanliness after the smoke

## RFC3339 Datetime Interval

The STAC `/search` payload uses RFC3339 datetime intervals:
- Full range: `2024-01-01T00:00:00Z/2024-03-31T23:59:59Z`
- Start only: `2024-01-01T00:00:00Z/..`
- End only: `../2024-03-31T23:59:59Z`

## Normal Tests Are Offline

The default `endpoints.json` has `active: false` for `earth_search`. Normal pytest and release verification scripts use simulation and do not require internet.

## Scope Limits

- No scoring changes
- No threshold changes
- No candidate generation changes
- No calibration changes
- No DB schema changes
- No UI changes
- No raster download
- No paid provider execution required
