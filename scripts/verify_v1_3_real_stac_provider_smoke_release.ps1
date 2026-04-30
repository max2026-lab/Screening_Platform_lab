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

# Run mocked STAC provider tests only (no network required)
$pytestResult = & uv run pytest tests\unit\test_stac_provider.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Mocked STAC provider tests failed.`n$pytestResult"
}

# Verify default endpoints config keeps real STAC inactive
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

# Verify stac_client.py uses POST /search and no raster download
$stacClientPath = Join-Path $repoRoot "src\lawful_anomaly_screening\sources\stac_client.py"
$stacClientText = Get-Content -Path $stacClientPath -Raw
if ($stacClientText -notmatch 'request\.Request\(.*method\s*=\s*"POST"') {
    throw "stac_client.py must use POST for /search requests"
}
if ($stacClientText -match 'download') {
    throw "stac_client.py must not contain raster download behavior"
}

# Verify docs contain expected safety boundaries
$docsPath = Join-Path $repoRoot "docs\V1_3_REAL_STAC_PROVIDER_SMOKE.md"
$docsText = Get-Content -Path $docsPath -Raw
$requiredPhrases = @(
    "metadata-only",
    "no raster download",
    "offline",
    "network"
)
foreach ($phrase in $requiredPhrases) {
    if ($docsText -notmatch $phrase) {
        throw "docs/V1_3_REAL_STAC_PROVIDER_SMOKE.md missing required phrase: $phrase"
    }
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

Write-Host "V1.3 real STAC provider smoke release verification passed."
