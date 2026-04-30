# V1.3 Real STAC Provider Smoke

This document describes the narrow real STAC metadata-only provider smoke path added in V1.3.

## What It Is

A configurable path to query real STAC endpoints (e.g., Earth Search) for metadata only, normalize returned items into the existing `discovered_scenes` format, and persist a deterministic `source_scene_manifest_hash`.

## What It Is Not

- It does not download raster assets
- It does not change scoring, thresholds, candidate generation, or calibration
- It does not change the DB schema
- It does not make real provider behavior the default for normal offline runs

## Configuration

Add real STAC fields to an endpoint definition in your endpoints config:

```json
{
  "primary": "earth_search",
  "fallbacks": [],
  "earth_search": {
    "provider": "earth-search",
    "role": "primary",
    "synchronous_only": true,
    "active": true,
    "base_url": "https://earth-search.aws.element84.com/v1",
    "search_path": "search",
    "collections": ["sentinel-2-l2a"],
    "timeout_seconds": 30,
    "max_items": 10,
    "metadata_only": true
  }
}
```

Required fields for real STAC mode:
- `active: true` — must be explicitly set to opt in
- `base_url` — the STAC API root URL
- `metadata_only: true` — confirms no raster downloads

Optional fields:
- `search_path` — defaults to `"search"`
- `collections` — list of collection IDs to query
- `timeout_seconds` — defaults to `30`
- `max_items` — defaults to `10`

## Behavior

When an endpoint has `active: true` and `base_url` set:

1. `discover_scenes` delegates to `query_stac_search`
2. The STAC `/search` endpoint is called with:
   - `bbox` derived deterministically from `aoi_hash`
   - `datetime` from `start_date`/`end_date`
   - `collections` from config
   - `limit` from config
3. Returned STAC items are normalized into:
   - `scene_id`
   - `acquired_at` (from `properties.datetime`)
   - `cloud_cover` (from `properties.eo:cloud_cover` or `properties.cloud_cover`)
   - `collection`
   - `provider_item_id`
4. Items are sorted by `scene_id` for deterministic manifest hashing
5. Scenes flow through existing `ManifestRepository.persist_manifest()` into:
   - `source_scene_manifests`
   - `discovered_scenes`

## Normal Tests Are Offline

The default `endpoints.json` has `active: false` for `earth_search`. Normal pytest uses simulation and does not require internet.

Mocked STAC provider tests validate normalization and HTTP handling without network calls.

## Live Smoke Requires Network

To run a live real STAC smoke test:

1. Create a temporary endpoints config with `active: true`
2. Set `LAWFUL_ANOMALY_ENDPOINTS_PATH` to that config
3. Run the normal operator flow:

```powershell
$env:LAWFUL_ANOMALY_ENDPOINTS_PATH = "C:\temp\active-stac-endpoints.json"
$env:LAWFUL_ANOMALY_DB_PATH = "C:\temp\stac-smoke.sqlite3"

lawful-anomaly init-db
lawful-anomaly create-run `
  --attestation present `
  --geofence clear `
  --run-id stac-smoke-001 `
  --aoi-path C:\Dev\Screening_Platform_lab\tests\fixtures\sample_aoi.geojson `
  --start-date 2024-01-01 `
  --end-date 2024-03-31
```

If the endpoint is reachable, `create-run` will:
- Query the real STAC `/search` endpoint
- Persist discovered scenes
- Produce a deterministic `source_scene_manifest_hash`

## Verification

After a live smoke run, verify rows were written:

```powershell
# Using sqlite3 directly
sqlite3 C:\temp\stac-smoke.sqlite3 "SELECT scene_id, acquired_at, cloud_cover FROM discovered_scenes;"
```

Also verify the manifest hash exists:

```powershell
sqlite3 C:\temp\stac-smoke.sqlite3 "SELECT source_scene_manifest_hash FROM source_scene_manifests;"
```

## Scope Limits

- No scoring changes
- No threshold changes
- No candidate generation changes
- No provider changes beyond this metadata-only query path
- No calibration changes
- No DB schema changes
- No UI changes
