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

# Run AOI and STAC bbox relevant tests only (no network required)
$pytestResult = & uv run pytest tests\unit\test_aoi_execution.py tests\unit\test_stac_provider.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "AOI/STAC bbox tests failed.`n$pytestResult"
}

# Verify AOI validation contains extract_bbox_from_geojson and coordinate validation
$aoiValidationPath = Join-Path $repoRoot "src\lawful_anomaly_screening\aoi\validation.py"
$aoiValidationText = Get-Content -Path $aoiValidationPath -Raw
if ($aoiValidationText -notmatch 'def extract_bbox_from_geojson') {
    throw "AOI validation must contain extract_bbox_from_geojson"
}
if ($aoiValidationText -notmatch 'invalid AOI coordinate') {
    throw "AOI validation must reject invalid coordinates with 'invalid AOI coordinate'"
}

# Verify STAC client includes bbox in payload when provided
$stacClientPath = Join-Path $repoRoot "src\lawful_anomaly_screening\sources\stac_client.py"
$stacClientText = Get-Content -Path $stacClientPath -Raw
if ($stacClientText -notmatch 'bbox: list\[float\] \| None = None') {
    throw "stac_client.py must accept bbox parameter"
}
if ($stacClientText -notmatch 'payload\["bbox"\] = bbox') {
    throw "stac_client.py must include bbox in POST payload"
}

# Verify earth_search fails active real STAC when no AOI bbox is provided
$earthSearchPath = Join-Path $repoRoot "src\lawful_anomaly_screening\sources\earth_search.py"
$earthSearchText = Get-Content -Path $earthSearchPath -Raw
if ($earthSearchText -notmatch 'real STAC active but no AOI bbox provided') {
    throw "earth_search.py must fail active real STAC when no AOI bbox is provided"
}

# Verify docs state V1.4 wires real AOI bbox into STAC /search
$docsPath = Join-Path $repoRoot "docs\V1_3_REAL_STAC_PROVIDER_SMOKE.md"
$docsText = Get-Content -Path $docsPath -Raw
$requiredDocPhrases = @(
    'V1.4 wires real AOI bbox into the STAC `/search`',
    'no raster download',
    'offline',
    'network'
)
foreach ($phrase in $requiredDocPhrases) {
    if ($docsText -notmatch [regex]::Escape($phrase)) {
        throw "docs/V1_3_REAL_STAC_PROVIDER_SMOKE.md missing required phrase: $phrase"
    }
}

# Verify operator_runbook references V1.4 AOI bbox STAC smoke
$runbookPath = Join-Path $repoRoot "docs\operator_runbook.md"
$runbookText = Get-Content -Path $runbookPath -Raw
if ($runbookText -notmatch 'V1.4.*AOI.*bbox.*STAC') {
    throw "docs/operator_runbook.md must reference V1.4 AOI bbox STAC smoke"
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
if ($endpoints.earth_search.PSObject.Properties.Name -contains "download") {
    throw "Default endpoints config must not contain raster download fields"
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

Write-Host "V1.4 real STAC AOI bbox smoke release verification passed."
