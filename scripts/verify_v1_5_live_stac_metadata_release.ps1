#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

# Run targeted offline tests
$pytestResult = & uv run pytest tests\unit\test_stac_provider.py tests\unit\test_aoi_execution.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted STAC/AOI tests failed.`n$pytestResult"
}

# Verify live smoke script exists
$liveSmokePath = Join-Path $repoRoot "scripts\smoke_live_v1_5_real_stac_metadata.ps1"
if (-not (Test-Path $liveSmokePath)) {
    throw "Live smoke script not found: $liveSmokePath"
}
$liveSmokeText = Get-Content -Path $liveSmokePath -Raw

# Verify opt-in guard
if ($liveSmokeText -notmatch 'LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE') {
    throw "Live smoke script missing opt-in guard"
}
if ($liveSmokeText -notmatch 'live STAC smoke requires LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE=1') {
    throw "Live smoke script missing exact refusal text"
}
if ($liveSmokeText -notmatch 'https://earth-search\.aws\.element84\.com/v1') {
    throw "Live smoke script does not use Earth Search endpoint"
}
if ($liveSmokeText -notmatch 'metadata_only') {
    throw "Live smoke script missing metadata_only"
}
if ($liveSmokeText -notmatch 'sentinel-2-l2a') {
    throw "Live smoke script missing sentinel-2-l2a collection"
}
if ($liveSmokeText -notmatch 'manifestDatetime') {
    throw "Live smoke script missing RFC3339 datetime check"
}
if ($liveSmokeText -notmatch 'manifestBbox') {
    throw "Live smoke script missing bbox check"
}
if ($liveSmokeText -notmatch 'discovered_scenes') {
    throw "Live smoke script missing discovered_scenes check"
}
if ($liveSmokeText -notmatch 'source_scene_manifests') {
    throw "Live smoke script missing source_scene_manifests check"
}
if ($liveSmokeText -notmatch 'Raster files found') {
    throw "Live smoke script missing no-raster-files check"
}

# Verify live smoke script refuses without opt-in
$noOptInProcess = Start-Process -FilePath "powershell" -ArgumentList "-ExecutionPolicy Bypass -File `"$liveSmokePath`"" -Wait -PassThru -WindowStyle Hidden -RedirectStandardError (Join-Path $env:TEMP "v15-no-opt-in-stderr.txt") -RedirectStandardOutput (Join-Path $env:TEMP "v15-no-opt-in-stdout.txt")
$noOptInExit = $noOptInProcess.ExitCode
$noOptInStdout = Get-Content -Path (Join-Path $env:TEMP "v15-no-opt-in-stdout.txt") -Raw -ErrorAction SilentlyContinue
$noOptInStderr = Get-Content -Path (Join-Path $env:TEMP "v15-no-opt-in-stderr.txt") -Raw -ErrorAction SilentlyContinue
$noOptInStr = "$noOptInStdout $noOptInStderr"
if ($noOptInExit -eq 0) {
    throw "Live smoke script must fail without opt-in, but exited 0"
}
if ($noOptInStr -notmatch 'live STAC smoke requires LAWFUL_ANOMALY_ALLOW_LIVE_STAC_SMOKE=1') {
    throw "Live smoke script refusal text missing from output"
}

# Verify docs exist
$v1_5DocsPath = Join-Path $repoRoot "docs\V1_5_LIVE_STAC_METADATA_SMOKE.md"
if (-not (Test-Path $v1_5DocsPath)) {
    throw "V1.5 docs not found: $v1_5DocsPath"
}
$v1_5DocsText = Get-Content -Path $v1_5DocsPath -Raw
$requiredDocPhrases = @(
    'live',
    'network',
    'metadata-only',
    'no raster download',
    'offline',
    'RFC3339'
)
foreach ($phrase in $requiredDocPhrases) {
    if ($v1_5DocsText -notmatch $phrase) {
        throw "docs/V1_5_LIVE_STAC_METADATA_SMOKE.md missing required phrase: $phrase"
    }
}

# Verify operator_runbook references V1.5
$runbookPath = Join-Path $repoRoot "docs\operator_runbook.md"
$runbookText = Get-Content -Path $runbookPath -Raw
if ($runbookText -notmatch 'V1\.5.*Live.*STAC.*Metadata.*Smoke') {
    throw "docs/operator_runbook.md must reference V1.5 Live Real STAC Metadata Smoke"
}
if ($runbookText -notmatch 'smoke_live_v1_5_real_stac_metadata\.ps1') {
    throw "docs/operator_runbook.md must reference live smoke script"
}

# Verify RFC3339 product fix remains present
$stacClientPath = Join-Path $repoRoot "src\lawful_anomaly_screening\sources\stac_client.py"
$stacClientText = Get-Content -Path $stacClientPath -Raw
if ($stacClientText -notmatch '_build_stac_datetime_interval') {
    throw "stac_client.py missing _build_stac_datetime_interval"
}

$stacTestPath = Join-Path $repoRoot "tests\unit\test_stac_provider.py"
$stacTestText = Get-Content -Path $stacTestPath -Raw
$rfc3339Patterns = @(
    '2024-01-01T00:00:00Z/2024-03-31T23:59:59Z',
    '2024-01-01T00:00:00Z/\.\.',
    '\.\./2024-03-31T23:59:59Z'
)
foreach ($pattern in $rfc3339Patterns) {
    if ($stacTestText -notmatch $pattern) {
        throw "test_stac_provider.py missing RFC3339 pattern: $pattern"
    }
}

# Verify default endpoints config keeps earth_search inactive
$endpointsPath = Join-Path $repoRoot "src\lawful_anomaly_screening\config\sources\endpoints.json"
$endpoints = Get-Content -Path $endpointsPath -Raw | ConvertFrom-Json
if ($endpoints.earth_search.active -ne $false) {
    throw "Default endpoints config must keep earth_search active=false"
}
if ($endpoints.earth_search.metadata_only -ne $true) {
    throw "Default endpoints config must keep earth_search metadata_only=true"
}

# Final repo cleanliness check
$repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($repoStatus) {
    throw "Repository is not clean after verification.`n$repoStatus"
}

$repoRemotes = (git -C $repoRoot remote -v | Out-String).Trim()
foreach ($forbidden in @("x-access-token", "ghp_", "github_pat_", "oauth", "token@")) {
    if ($repoRemotes -match $forbidden) {
        throw "git remote -v contains forbidden credential pattern: $forbidden"
    }
}

Write-Host "V1.5 live STAC metadata release verification passed."
