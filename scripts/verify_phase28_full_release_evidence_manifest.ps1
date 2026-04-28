#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [switch] $AllowNonMain,
    [string] $OutputDir = (Join-Path (Get-Location).Path ".release-evidence\phase28-full-release-evidence-manifest"),
    [switch] $Overwrite
)

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

function Get-SHA256Hex {
    param([Parameter(Mandatory = $true)][string] $Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash) -replace "-", "").ToLower()
}

function Get-FileSHA256Hex {
    param([Parameter(Mandatory = $true)][string] $FilePath)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.IO.File]::ReadAllBytes($FilePath))
    return ([System.BitConverter]::ToString($hash) -replace "-", "").ToLower()
}

function Write-LfText {
    param(
        [Parameter(Mandatory = $true)][string] $Path,
        [Parameter(Mandatory = $true)][string] $Content
    )
    $normalized = $Content -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $normalized, $utf8NoBom)
}

# Pre-flight checks
Test-NoEmbeddedCredentials

$branch = (git -C $repoRoot rev-parse --abbrev-ref HEAD).Trim()
if ((-not $AllowNonMain) -and ($branch -ne "main")) {
    throw "Current branch is '$branch', expected 'main'. Use -AllowNonMain to override."
}

$statusBefore = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($statusBefore) {
    throw "Repository is not clean before running Phase 27 chain.`n$statusBefore"
}

$headCommit = (git -C $repoRoot rev-parse HEAD).Trim()
$remoteUrl = ((git -C $repoRoot remote get-url origin 2>$null) | Out-String).Trim()
$remoteUrlSanitized = if ($remoteUrl) { $remoteUrl } else { "unknown" }

# Run Phase 27 chain
$phase27Script = Join-Path (Join-Path $repoRoot "scripts") "verify_phase27_full_release_verification_chain.ps1"
if (-not (Test-Path $phase27Script)) {
    throw "Phase 27 script not found: $phase27Script"
}

& powershell -ExecutionPolicy Bypass -File $phase27Script
if ($LASTEXITCODE -ne 0) {
    throw "Phase 27 full release verification chain failed (exit $LASTEXITCODE)"
}

# Post-flight checks
$statusAfter = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($statusAfter) {
    throw "Repository is not clean after running Phase 27 chain.`n$statusAfter"
}

Test-NoEmbeddedCredentials

# Build manifest
$generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")

$phasesVerified = @(
    "phase5", "phase6", "phase7", "phase8", "phase9", "phase10",
    "phase11", "phase12", "phase13", "phase14", "phase15", "phase16",
    "phase17", "phase18", "phase19", "phase20", "phase21", "phase22",
    "phase23", "phase24", "phase25", "phase26"
)

$manifest = [ordered]@{
    evidence_type = "full_release_evidence_manifest"
    evidence_version = 1
    status = "passed"
    reasons = @("Phase 27 full release verification chain completed successfully")
    repo_root = $repoRoot
    branch = $branch
    head_commit = $headCommit
    remote_url_sanitized = $remoteUrlSanitized
    baseline_tag = "baseline-phase27-full-release-verification-chain-2026-04-27"
    verification_chain_script = "scripts/verify_phase27_full_release_verification_chain.ps1"
    verification_chain_status = "passed"
    phases_verified = $phasesVerified
    pytest_status = "passed"
    git_status_clean_before = $true
    git_status_clean_after = $true
    remote_credentials_clean_before = $true
    remote_credentials_clean_after = $true
    generated_at_utc = $generatedAtUtc
    files = @(
        "full_release_evidence_manifest.json",
        "full_release_evidence_manifest.md",
        "SHA256SUMS.txt"
    )
    bundle_file_manifest_policy = "Bundle file content hashes are recorded in SHA256SUMS.txt to avoid self-referential JSON hashing."
}

# Compute manifest_hash excluding generated_at_utc, repo_root, remote_url_sanitized, files, bundle_file_manifest_policy
$hashPayload = [ordered]@{
    evidence_type = $manifest.evidence_type
    evidence_version = $manifest.evidence_version
    status = $manifest.status
    reasons = $manifest.reasons
    branch = $manifest.branch
    head_commit = $manifest.head_commit
    baseline_tag = $manifest.baseline_tag
    verification_chain_script = $manifest.verification_chain_script
    verification_chain_status = $manifest.verification_chain_status
    phases_verified = $manifest.phases_verified
    pytest_status = $manifest.pytest_status
    git_status_clean_before = $manifest.git_status_clean_before
    git_status_clean_after = $manifest.git_status_clean_after
    remote_credentials_clean_before = $manifest.remote_credentials_clean_before
    remote_credentials_clean_after = $manifest.remote_credentials_clean_after
}

$manifest["manifest_hash"] = Get-SHA256Hex -Text ($hashPayload | ConvertTo-Json -Depth 10)

# Output dir handling
$outputDirPath = $OutputDir
if (Test-Path $outputDirPath) {
    $children = Get-ChildItem -Path $outputDirPath -Force
    if ($children -and (-not $Overwrite)) {
        throw "Output directory exists and is not empty: $outputDirPath. Use -Overwrite to replace."
    }
} else {
    New-Item -ItemType Directory -Path $outputDirPath -Force | Out-Null
}

$jsonPath = Join-Path $outputDirPath "full_release_evidence_manifest.json"
$mdPath = Join-Path $outputDirPath "full_release_evidence_manifest.md"
$sumsPath = Join-Path $outputDirPath "SHA256SUMS.txt"

$jsonText = ($manifest | ConvertTo-Json -Depth 10) + "`n"

$phasesMd = ($phasesVerified | ForEach-Object { "- $_" }) -join "`n"
$reasonsMd = ($manifest.reasons | ForEach-Object { "- $_" }) -join "`n"

$mdLines = @(
    "# Full Release Evidence Manifest"
    ""
    "- Status: ``$($manifest.status)``"
    "- Head commit: ``$($manifest.head_commit)``"
    "- Baseline tag: ``$($manifest.baseline_tag)``"
    "- Verification chain: ``$($manifest.verification_chain_script)``"
    "- Pytest: ``$($manifest.pytest_status)``"
    "- Git clean before: ``$($manifest.git_status_clean_before)``"
    "- Git clean after: ``$($manifest.git_status_clean_after)``"
    "- Remote credentials clean before: ``$($manifest.remote_credentials_clean_before)``"
    "- Remote credentials clean after: ``$($manifest.remote_credentials_clean_after)``"
    "- Manifest hash: ``$($manifest.manifest_hash)``"
    ""
    "## Phases Verified"
    ""
) + $phasesMd.Split("`n") + @("", "## Reasons", "") + $reasonsMd.Split("`n")
$mdText = ($mdLines -join "`n") + "`n"

Write-LfText -Path $jsonPath -Content $jsonText
Write-LfText -Path $mdPath -Content $mdText

$jsonHash = Get-FileSHA256Hex -FilePath $jsonPath
$mdHash = Get-FileSHA256Hex -FilePath $mdPath
$sumsText = "$jsonHash  full_release_evidence_manifest.json`n$mdHash  full_release_evidence_manifest.md`n"
Write-LfText -Path $sumsPath -Content $sumsText

# Final repo cleanliness check
$finalStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($finalStatus) {
    throw "Repository is not clean after writing evidence manifest.`n$finalStatus"
}

Write-Host "Phase 28 full release evidence manifest written to: $outputDirPath"
Write-Host "Phase 28 full release evidence manifest passed."
