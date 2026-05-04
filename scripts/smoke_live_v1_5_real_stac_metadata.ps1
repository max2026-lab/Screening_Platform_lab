#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Opt-in guard: live STAC smoke must be explicitly allowed
if ($env:LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE -ne "1") {
    throw "live STAC smoke requires LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE=1"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentDir = (Resolve-Path ".").Path
if ($currentDir -ne $repoRoot) {
    throw "Run this script from repo root: $repoRoot"
}

$repoLocalCliPath = Join-Path $repoRoot ".venv\Scripts\lawful-anomaly.exe"
if (-not (Test-Path $repoLocalCliPath)) {
    throw "Repo-local lawful-anomaly CLI not found at $repoLocalCliPath.`nRun: uv sync`nRun: uv pip install -e $repoRoot"
}
$env:PATH = "$(Split-Path -Parent $repoLocalCliPath);$env:PATH"
$lawfulAnomalyCommand = Get-Command lawful-anomaly -ErrorAction SilentlyContinue
if ($null -eq $lawfulAnomalyCommand) {
    throw "Required command not found after PATH update: lawful-anomaly"
}
Write-Host "Using lawful-anomaly: $($lawfulAnomalyCommand.Source)"

# Temp working directory outside repo root
$tempDir = "C:\temp\screening-v1-5-live-stac-smoke"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Write AOI GeoJSON (small bbox in central Europe, likely to have Sentinel-2 coverage)
$aoiGeoJson = @"
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[12.0,41.0],[12.1,41.0],[12.1,41.1],[12.0,41.1],[12.0,41.0]]]}}]}
"@
$aoiPath = Join-Path $tempDir "aoi.geojson"
[System.IO.File]::WriteAllText($aoiPath, $aoiGeoJson, [System.Text.UTF8Encoding]::new($false))

# Write temp endpoint config with active real STAC
$endpointsConfig = @"
{"primary":"earth_search","fallbacks":[],"earth_search":{"provider":"earth-search","role":"primary","synchronous_only":true,"active":true,"base_url":"https://earth-search.aws.element84.com/v1","search_path":"search","collections":["sentinel-2-l2a"],"timeout_seconds":30,"max_items":5,"metadata_only":true}}
"@
$endpointsPath = Join-Path $tempDir "active-endpoints.json"
[System.IO.File]::WriteAllText($endpointsPath, $endpointsConfig, [System.Text.UTF8Encoding]::new($false))

# Set env for this run
$env:LAWFUL_ANOMALY_ENDPOINTS_PATH = $endpointsPath
$env:LAWFUL_ANOMALY_DB_PATH = Join-Path $tempDir "live-stac-smoke.sqlite3"

# Run init-db
& lawful-anomaly init-db
if ($LASTEXITCODE -ne 0) {
    throw "init-db failed with exit code $LASTEXITCODE"
}

# Run create-run
$startDate = "2024-01-01"
$endDate = "2024-03-31"
$runOutput = & lawful-anomaly create-run `
    --attestation present `
    --geofence clear `
    --run-id live-stac-smoke-001 `
    --aoi-path $aoiPath `
    --start-date $startDate `
    --end-date $endDate

if ($LASTEXITCODE -ne 0) {
    throw "create-run failed with exit code $LASTEXITCODE`n$runOutput"
}

# Parse JSON output
$runRecord = $runOutput | ConvertFrom-Json
if (-not $runRecord) {
    throw "create-run output was not valid JSON"
}

# Verify basic run fields
if ($runRecord.run_id -ne "live-stac-smoke-001") {
    throw "Expected run_id 'live-stac-smoke-001', got '$($runRecord.run_id)'"
}
if ($runRecord.source_endpoint_id -ne "earth_search") {
    throw "Expected source_endpoint_id 'earth_search', got '$($runRecord.source_endpoint_id)'"
}
if (-not $runRecord.source_scene_manifest_hash) {
    throw "source_scene_manifest_hash is missing"
}
$manifestHash = $runRecord.source_scene_manifest_hash

# Verify manifest file exists
# Note: create-run output does not include manifest_path; query DB for it
$dbPathForQuery = $env:LAWFUL_ANOMALY_DB_PATH
$manifestPath = & python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT manifest_path FROM source_scene_manifests WHERE source_scene_manifest_hash=?',(sys.argv[2],)).fetchone()[0]); c.close()" $dbPathForQuery $manifestHash
if (-not $manifestPath) {
    throw "Manifest path not found in DB for manifest hash $manifestHash"
}
if (-not (Test-Path $manifestPath)) {
    throw "Manifest file not found at $manifestPath"
}
$manifestJson = Get-Content -Path $manifestPath -Raw | ConvertFrom-Json

# Verify manifest query_parameters contain bbox
if (-not $manifestJson.query_parameters) {
    throw "manifest JSON missing query_parameters"
}
$qp = $manifestJson.query_parameters
if (-not $qp.bbox) {
    throw "manifest query_parameters missing bbox"
}
$manifestBbox = $qp.bbox
if ($manifestBbox.Count -ne 4) {
    throw "manifest bbox must have 4 elements, got $($manifestBbox.Count)"
}
# Allow small floating point differences
$aoiBbox = @(12.0, 41.0, 12.1, 41.1)
for ($i = 0; $i -lt 4; $i++) {
    $diff = [math]::Abs($manifestBbox[$i] - $aoiBbox[$i])
    if ($diff -gt 0.001) {
        throw "manifest bbox[$i] mismatch: expected $($aoiBbox[$i]), got $($manifestBbox[$i])"
    }
}

# Verify datetime is RFC3339 interval, not YYYY-MM-DD/YYYY-MM-DD
$manifestDatetime = $qp.datetime
if (-not $manifestDatetime) {
    throw "manifest query_parameters missing datetime"
}
if ($manifestDatetime -match '^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$') {
    throw "manifest datetime is not RFC3339 interval: $manifestDatetime"
}
if (-not ($manifestDatetime -match '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')) {
    throw "manifest datetime is not a valid RFC3339 interval: $manifestDatetime"
}

# Verify collections
$manifestCollections = $qp.collections
if (-not $manifestCollections -or -not ($manifestCollections -contains "sentinel-2-l2a")) {
    throw "manifest query_parameters collections must contain sentinel-2-l2a"
}

# Verify scenes exist
$scenes = $manifestJson.scenes
if (-not $scenes -or $scenes.Count -eq 0) {
    throw "manifest JSON has no scenes"
}

# Verify each scene has required fields
$hasProviderItemId = $false
$hasCollection = $false
foreach ($scene in $scenes) {
    if (-not $scene.scene_id) {
        throw "manifest scene missing scene_id"
    }
    if (-not $scene.acquired_at) {
        throw "manifest scene missing acquired_at"
    }
    if ($scene.provider_item_id) {
        $hasProviderItemId = $true
    }
    if ($scene.collection -eq "sentinel-2-l2a") {
        $hasCollection = $true
    }
}
if (-not $hasProviderItemId) {
    throw "no manifest scene has provider_item_id"
}
if (-not $hasCollection) {
    throw "no manifest scene has collection sentinel-2-l2a"
}

# Verify no raster asset files downloaded into temp dir
$rasterExtensions = @("*.tif", "*.tiff", "*.jp2", "*.png", "*.jpg", "*.jpeg")
foreach ($ext in $rasterExtensions) {
    $rasterFiles = Get-ChildItem -Path $tempDir -Filter $ext -Recurse -ErrorAction SilentlyContinue
    if ($rasterFiles) {
        throw "Raster files found in temp dir: $($rasterFiles.FullName -join ', ')"
    }
}

# Verify DB rows exist
$dbPath = $env:LAWFUL_ANOMALY_DB_PATH
if (-not (Test-Path $dbPath)) {
    throw "DB file not found at $dbPath"
}

$sceneCount = & python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('SELECT COUNT(*) FROM discovered_scenes WHERE source_scene_manifest_hash=?',(sys.argv[2],)).fetchone()[0]; c.close(); print(r)" $dbPath $manifestHash
if ($sceneCount -eq 0 -or $sceneCount -eq "0") {
    throw "No discovered_scenes rows found for manifest hash $manifestHash"
}
Write-Host "Discovered scenes count: $sceneCount"

$manifestRowCount = & python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('SELECT COUNT(*) FROM source_scene_manifests WHERE source_scene_manifest_hash=?',(sys.argv[2],)).fetchone()[0]; c.close(); print(r)" $dbPath $manifestHash
if ($manifestRowCount -eq 0 -or $manifestRowCount -eq "0") {
    throw "No source_scene_manifests row found for manifest hash $manifestHash"
}
Write-Host "Source scene manifest row exists."

# Final repo cleanliness check
$repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($repoStatus) {
    throw "Repository is not clean after smoke.`n$repoStatus"
}

$repoRemotes = (git -C $repoRoot remote -v | Out-String).Trim()
foreach ($forbidden in @("x-access-token", "ghp_", "github_pat_", "oauth", "token@")) {
    if ($repoRemotes -match $forbidden) {
        throw "git remote -v contains forbidden credential pattern: $forbidden"
    }
}

Write-Host "V1.5 live real STAC metadata smoke passed."
