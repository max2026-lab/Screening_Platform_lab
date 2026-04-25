#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentDir = (Resolve-Path ".").Path
if ($currentDir -ne $repoRoot) {
    throw "Run this script from repo root: $repoRoot"
}

if (-not (Get-Command lawful-anomaly -ErrorAction SilentlyContinue)) {
    throw "Required command not found: lawful-anomaly. Install the package first (for example, `uv tool install C:\Dev\Screening_Platform_lab`)."
}

$helpOutput = & lawful-anomaly --help 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "lawful-anomaly --help failed.`n$($helpOutput -join [Environment]::NewLine)"
}

function Invoke-LawfulJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    $output = & lawful-anomaly @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "lawful-anomaly $($Arguments -join ' ') failed.`n$($output -join [Environment]::NewLine)"
    }

    $text = ($output | Out-String).Trim()
    if (-not $text) {
        throw "lawful-anomaly $($Arguments -join ' ') returned empty output"
    }
    return ($text | ConvertFrom-Json)
}

$baseTempRoot = Join-Path $env:TEMP ("phase5-release-verify-" + [guid]::NewGuid().ToString())
$normalFlowRoot = Join-Path $baseTempRoot "normal"
$fallbackFlowRoot = Join-Path $baseTempRoot "fallback"
New-Item -ItemType Directory -Path $normalFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $fallbackFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    # Flow A: normal operator smoke
    Set-Location $normalFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $normalFlowRoot "release-normal.sqlite3"

    $initOutput = & lawful-anomaly init-db 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Flow A init-db failed.`n$($initOutput -join [Environment]::NewLine)"
    }

    $normalCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "release-normal-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($normalCreate.source_endpoint_id -ne "earth_search") {
        throw "Flow A create-run expected source_endpoint_id=earth_search, got $($normalCreate.source_endpoint_id)"
    }

    $normalExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "release-normal-001")
    if ($normalExecute.source_endpoint_id -ne "earth_search") {
        throw "Flow A execute-run expected source_endpoint_id=earth_search, got $($normalExecute.source_endpoint_id)"
    }

    $topCandidateId = [string]$normalExecute.top_candidate_id
    if (-not $topCandidateId) {
        throw "Flow A execute-run did not return top_candidate_id"
    }
    $null = Invoke-LawfulJson -Arguments @("review-show", "--candidate-id", $topCandidateId)
    $null = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "release-normal-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )

    # Flow B: provider fallback smoke
    Set-Location $fallbackFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $fallbackConfigPath = Join-Path $fallbackFlowRoot "fallback-endpoints.json"
    @'
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
'@ | Set-Content -LiteralPath $fallbackConfigPath -Encoding UTF8

    $env:LAWFUL_ANOMALY_ENDPOINTS_PATH = $fallbackConfigPath
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $fallbackFlowRoot "release-fallback.sqlite3"

    $fallbackInitOutput = & lawful-anomaly init-db 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Flow B init-db failed.`n$($fallbackInitOutput -join [Environment]::NewLine)"
    }

    $fallbackCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "release-fallback-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if (-not $fallbackCreate.PSObject.Properties["fallback_diagnostics"]) {
        throw "Flow B create-run missing fallback_diagnostics"
    }
    $diagnostics = $fallbackCreate.fallback_diagnostics
    $attempted = @($diagnostics.attempted_endpoint_ids)
    if ($attempted.Count -ne 2 -or $attempted[0] -ne "sim_empty" -or $attempted[1] -ne "cdse") {
        throw "Flow B attempted_endpoint_ids expected [sim_empty, cdse], got [$($attempted -join ', ')]"
    }
    if ($diagnostics.selected_endpoint_id -ne "cdse") {
        throw "Flow B selected_endpoint_id expected cdse, got $($diagnostics.selected_endpoint_id)"
    }

    $fallbackExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "release-fallback-001")
    if ($fallbackExecute.source_endpoint_id -ne "cdse") {
        throw "Flow B execute-run expected source_endpoint_id=cdse, got $($fallbackExecute.source_endpoint_id)"
    }

    # Outside-cwd safety checks
    if (Test-Path (Join-Path $normalFlowRoot "config")) {
        throw "Flow A copied config into outside working directory"
    }
    if (Test-Path (Join-Path $fallbackFlowRoot "config")) {
        throw "Flow B copied config into outside working directory"
    }
    if (Test-Path (Join-Path $normalFlowRoot "sitecustomize.py")) {
        throw "Flow A created sitecustomize.py in outside working directory"
    }
    if (Test-Path (Join-Path $fallbackFlowRoot "sitecustomize.py")) {
        throw "Flow B created sitecustomize.py in outside working directory"
    }

    # Final repo cleanliness check
    Set-Location $repoRoot
    $repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
    if ($repoStatus) {
        throw "Repository is not clean after verification.`n$repoStatus"
    }
}
finally {
    Set-Location $originalLocation
}

Write-Host "Phase 5 release verification passed."
