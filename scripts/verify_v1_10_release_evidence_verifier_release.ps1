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
    foreach ($pattern in @("x-access-token", "ghp_", "github_pat_", "oauth", "token@")) {
        if ($remoteOutput -match $pattern) {
            throw "git remote -v contains forbidden credential pattern: $pattern"
        }
    }
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

$pytestResult = & uv run pytest tests\integration\test_release_evidence_verify_cli.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted release evidence verifier CLI tests failed.`n$pytestResult"
}

$cliPath = Join-Path $repoRoot "src\lawful_anomaly_screening\cli.py"
$cliText = Get-Content -Path $cliPath -Raw
if ($cliText -notmatch 'release-evidence-verify') {
    throw "cli.py missing release-evidence-verify command"
}

$verifierPath = Join-Path $repoRoot "src\lawful_anomaly_screening\releases\evidence_verifier.py"
if (-not (Test-Path $verifierPath)) {
    throw "evidence_verifier.py not found"
}
$verifierText = Get-Content -Path $verifierPath -Raw
foreach ($pattern in @(
    'full_release_evidence_manifest\.json',
    'full_release_evidence_manifest\.md',
    'SHA256SUMS\.txt',
    'sha256',
    'render_release_evidence_verify_markdown',
    'verify_release_evidence'
)) {
    if ($verifierText -notmatch $pattern) {
        throw "evidence_verifier.py missing required pattern: $pattern"
    }
}

$phase28Script = Join-Path $repoRoot "scripts\verify_phase28_full_release_evidence_manifest.ps1"
& powershell -ExecutionPolicy Bypass -File $phase28Script -AllowNonMain -Overwrite
if ($LASTEXITCODE -ne 0) {
    throw "Phase 28 full release evidence manifest generation failed."
}

$evidenceDir = Join-Path $repoRoot ".release-evidence\phase28-full-release-evidence-manifest"
if (-not (Test-Path $evidenceDir)) {
    throw "Expected evidence directory not found: $evidenceDir"
}

$verifyResult = & lawful-anomaly release-evidence-verify --evidence-dir $evidenceDir 2>&1
$verifyExit = $LASTEXITCODE
if ($verifyExit -ne 0) {
    throw "release-evidence-verify failed with exit $verifyExit.`n$verifyResult"
}
$verifyJson = $verifyResult | Out-String | ConvertFrom-Json
if ($verifyJson.status -ne "pass") {
    throw "release-evidence-verify status is not pass.`n$verifyResult"
}
if ($verifyJson.required_files_present -ne $true) {
    throw "required_files_present is not true"
}
if ($verifyJson.json_manifest_valid -ne $true) {
    throw "json_manifest_valid is not true"
}
if ($verifyJson.markdown_manifest_valid -ne $true) {
    throw "markdown_manifest_valid is not true"
}
if ($verifyJson.sha256sums_valid -ne $true) {
    throw "sha256sums_valid is not true"
}

$markdownResult = & lawful-anomaly release-evidence-verify --evidence-dir $evidenceDir --output markdown 2>&1
$markdownExit = $LASTEXITCODE
if ($markdownExit -ne 0) {
    throw "release-evidence-verify markdown output failed with exit $markdownExit.`n$markdownResult"
}
if ($markdownResult -notmatch 'Release Evidence Verification') {
    throw "Markdown output missing report header.`n$markdownResult"
}
if ($markdownResult -notmatch 'Status: `pass`') {
    throw "Markdown output missing pass status.`n$markdownResult"
}

$env:LAWFUL_ANOMALY_DB_PATH = "C:\temp\screening-v1-10-nonexistent.sqlite3"
$noDbResult = & lawful-anomaly release-evidence-verify --evidence-dir $evidenceDir 2>&1
$noDbExit = $LASTEXITCODE
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
if ($noDbExit -ne 0) {
    throw "release-evidence-verify with nonexistent DB failed with exit $noDbExit.`n$noDbResult"
}
$noDbJson = $noDbResult | Out-String | ConvertFrom-Json
if ($noDbJson.status -ne "pass") {
    throw "release-evidence-verify with nonexistent DB status is not pass.`n$noDbResult"
}

$tempDir = "C:\temp\screening-v1-10-release-evidence-verify"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
Copy-Item -Recurse -Force $evidenceDir $tempDir

$tamperedJsonPath = Join-Path $tempDir "full_release_evidence_manifest.json"
$tamperedJson = Get-Content -Path $tamperedJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
$tamperedJson.status = "tampered"
[System.IO.File]::WriteAllText(
    $tamperedJsonPath,
    (($tamperedJson | ConvertTo-Json -Depth 10) + "`n") -replace "`r`n", "`n",
    [System.Text.UTF8Encoding]::new($false)
)

$failResult = & lawful-anomaly release-evidence-verify --evidence-dir $tempDir 2>&1
$failExit = $LASTEXITCODE
if ($failExit -eq 0) {
    throw "Tampered release evidence verification should have failed but returned 0.`n$failResult"
}
$failJson = $failResult | Out-String | ConvertFrom-Json
if ($failJson.status -ne "fail") {
    throw "Tampered release evidence verification status is not fail.`n$failResult"
}
if (-not ($failJson.reasons | Where-Object { $_ -match "SHA256 mismatch|Malformed SHA256SUMS|Unexpected checksum entry" })) {
    throw "Tampered release evidence verification reasons do not mention checksum failure.`n$failResult"
}

Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue

$repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
if ($repoStatus) {
    throw "Repository is not clean after verification.`n$repoStatus"
}

Test-NoEmbeddedCredentials

Write-Host "V1.10 release evidence verifier release verification passed."
