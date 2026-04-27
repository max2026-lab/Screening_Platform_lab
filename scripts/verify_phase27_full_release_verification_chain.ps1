#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentDir = (Resolve-Path ".").Path
if ($currentDir -ne $repoRoot) {
    throw "Run this script from repo root: $repoRoot"
}

function Test-NoEmbeddedCredentials {
    $remoteOutput = (git -C $repoRoot remote -v | Out-String)
    $patterns = @("x-access-token", "ghp_", "github_pat_", "oauth", "token@")
    foreach ($pattern in $patterns) {
        if ($remoteOutput -match $pattern) {
            throw "git remote -v contains embedded credential pattern: $pattern"
        }
    }
}

function Invoke-Stage {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [scriptblock] $Action
    )

    try {
        & $Action
        Write-Host "PASS  $Name"
    }
    catch {
        Write-Host "FAIL  $Name"
        throw
    }
}

# Pre-flight credential check
Test-NoEmbeddedCredentials

Invoke-Stage -Name "uv sync" -Action {
    & uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed (exit $LASTEXITCODE)" }
}

Invoke-Stage -Name "uv pip install -e $repoRoot" -Action {
    & uv pip install -e $repoRoot
    if ($LASTEXITCODE -ne 0) { throw "uv pip install failed (exit $LASTEXITCODE)" }
}

$repoLocalCliPath = Join-Path $repoRoot ".venv\Scripts\lawful-anomaly.exe"
if (-not (Test-Path $repoLocalCliPath)) {
    throw "Repo-local lawful-anomaly CLI not found at $repoLocalCliPath after install"
}
Write-Host "Using lawful-anomaly: $repoLocalCliPath"

Invoke-Stage -Name "uv run pytest" -Action {
    & uv run pytest
    if ($LASTEXITCODE -ne 0) { throw "pytest failed (exit $LASTEXITCODE)" }
}

$scripts = @(
    "verify_phase5_release.ps1",
    "verify_phase6_legal_release.ps1",
    "verify_phase7_composite_release.ps1",
    "verify_phase8_reproducibility_release.ps1",
    "verify_phase9_scoring_explainability_release.ps1",
    "verify_phase10_export_audit_release.ps1",
    "verify_phase11_acceptance_release.ps1",
    "verify_phase12_paid_archive_release.ps1",
    "verify_phase13_calibration_release.ps1",
    "verify_phase14_calibration_policy_release.ps1",
    "verify_phase15_calibration_label_release.ps1",
    "verify_phase16_label_pack_manifest_release.ps1",
    "verify_phase17_calibration_label_artifact_release.ps1",
    "verify_phase18_calibration_label_artifact_verify_release.ps1",
    "verify_phase19_calibration_artifact_registry_release.ps1",
    "verify_phase20_calibration_registry_snapshot_release.ps1",
    "verify_phase21_calibration_registry_snapshot_verify_release.ps1",
    "verify_phase22_calibration_registry_snapshot_diff_release.ps1",
    "verify_phase23_calibration_registry_snapshot_diff_export_release.ps1",
    "verify_phase24_calibration_registry_snapshot_diff_export_verify_release.ps1",
    "verify_phase25_calibration_registry_diff_acceptance_gate_release.ps1",
    "verify_phase26_calibration_signoff_evidence_bundle_release.ps1"
)

foreach ($scriptName in $scripts) {
    $scriptPath = Join-Path (Join-Path $repoRoot "scripts") $scriptName
    if (-not (Test-Path $scriptPath)) {
        throw "Release script not found: $scriptPath"
    }
    Invoke-Stage -Name $scriptName -Action {
        & powershell -ExecutionPolicy Bypass -File $scriptPath
        if ($LASTEXITCODE -ne 0) { throw "$scriptName failed (exit $LASTEXITCODE)" }
    }
}

Invoke-Stage -Name "git status --porcelain" -Action {
    $status = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
    if ($status) {
        throw "Repository is not clean after full verification chain.`n$status"
    }
}

Invoke-Stage -Name "git remote -v credential check" -Action {
    Test-NoEmbeddedCredentials
}

Write-Host "Phase 27 full release verification chain passed."
