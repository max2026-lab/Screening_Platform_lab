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

$pytestResult = & uv run pytest tests\integration\test_export_bundle_verify_cli.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted export bundle verify CLI tests failed.`n$pytestResult"
}

$cliPath = Join-Path $repoRoot "src\lawful_anomaly_screening\cli.py"
$cliText = Get-Content -Path $cliPath -Raw
if ($cliText -notmatch 'export-bundle-verify') {
    throw "cli.py missing export-bundle-verify command"
}

$verifierPath = Join-Path $repoRoot "src\lawful_anomaly_screening\exports\bundle_verifier.py"
if (-not (Test-Path $verifierPath)) {
    throw "bundle_verifier.py not found"
}
$verifierText = Get-Content -Path $verifierPath -Raw
$verifierPatterns = @(
    'v1\.7_report_bundle_manifest',
    'bundle_sha256',
    'bundle_members',
    'SHA256SUMS\.txt',
    'audit_manifest\.json',
    'forbidden geometry key'
)
foreach ($pattern in $verifierPatterns) {
    if ($verifierText -notmatch $pattern) {
        throw "bundle_verifier.py missing required pattern: $pattern"
    }
}

$tempDir = "C:\temp\screening-v1-8-export-bundle-verify-cli-release"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$env:LAWFUL_ANOMALY_DB_PATH = "$tempDir\test.sqlite3"

$bootstrap = @"
import sys
sys.path.insert(0, r'$repoRoot')
from pathlib import Path
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db

db_path = Path(r'$tempDir\test.sqlite3')
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_8_default',
    score_formula_version='v1.8.0-phase0',
    source_scene_manifest_hash='manifest-hash-001',
    source_endpoint_id='earth_search',
    run_id='run-001',
    manifest_path='data/manifests/manifest-hash-001.json',
    run_status='completed',
    aoi_hash='aoi-hash-001',
    start_date='2024-01-01',
    end_date='2024-03-31',
    legal_gate={
        'attestation_status': 'present',
        'geofence_status': 'clear',
        'decision': 'pass',
        'reason': '',
        'evaluated_at': '2024-01-01T00:00:00Z',
    },
)
print('BOOTSTRAP_OK')
"@

$bootstrapResult = & uv run python -c $bootstrap
if ($LASTEXITCODE -ne 0) {
    throw "DB bootstrap failed.`n$bootstrapResult"
}

Push-Location $tempDir
$exportResult = & lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted 2>&1
Pop-Location
$exportExit = $LASTEXITCODE
if ($exportExit -ne 0) {
    throw "export-create failed with exit $exportExit.`n$exportResult"
}
$exportJson = $exportResult | Out-String | ConvertFrom-Json

$manifestPath = Join-Path $tempDir $exportJson.bundle_manifest_path
if (-not (Test-Path $manifestPath)) {
    throw "Sidecar manifest not found at $manifestPath"
}

# Positive smoke: verify bundle
Push-Location $tempDir
$verifyResult = & lawful-anomaly export-bundle-verify --bundle-manifest-path $exportJson.bundle_manifest_path --export-root . 2>&1
Pop-Location
$verifyExit = $LASTEXITCODE
if ($verifyExit -ne 0) {
    throw "export-bundle-verify failed with exit $verifyExit.`n$verifyResult"
}
$verifyJson = $verifyResult | Out-String | ConvertFrom-Json
if ($verifyJson.status -ne "pass") {
    throw "export-bundle-verify status is not pass.`n$verifyResult"
}
if ($verifyJson.bundle_sha256_valid -ne $true) {
    throw "bundle_sha256_valid is not true"
}
if ($verifyJson.bundle_members_valid -ne $true) {
    throw "bundle_members_valid is not true"
}
if ($verifyJson.sidecar_files_valid -ne $true) {
    throw "sidecar_files_valid is not true"
}
if ($verifyJson.sha256sums_valid -ne $true) {
    throw "sha256sums_valid is not true"
}
if ($verifyJson.forbidden_geometry_keys_absent -ne $true) {
    throw "forbidden_geometry_keys_absent is not true"
}

# No DB access regression
$env:LAWFUL_ANOMALY_DB_PATH = "$tempDir\nonexistent.sqlite3"
Push-Location $tempDir
$noDbResult = & lawful-anomaly export-bundle-verify --bundle-manifest-path $exportJson.bundle_manifest_path --export-root . 2>&1
Pop-Location
$noDbExit = $LASTEXITCODE
if ($noDbExit -ne 0) {
    throw "export-bundle-verify with nonexistent DB failed with exit $noDbExit.`n$noDbResult"
}
$noDbJson = $noDbResult | Out-String | ConvertFrom-Json
if ($noDbJson.status -ne "pass") {
    throw "export-bundle-verify with nonexistent DB status is not pass.`n$noDbResult"
}
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

# Negative smoke: tamper bundle_sha256
$sidecar = Get-Content -Path $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sidecar.bundle_sha256 = "0" * 64
$tamperedPath = "$tempDir\tampered.manifest.json"
$tamperedJson = $sidecar | ConvertTo-Json -Depth 10 -Compress
[System.IO.File]::WriteAllText($tamperedPath, $tamperedJson, [System.Text.UTF8Encoding]::new($false))

Push-Location $tempDir
$failResult = & lawful-anomaly export-bundle-verify --bundle-manifest-path $tamperedPath --export-root . 2>&1
Pop-Location
$failExit = $LASTEXITCODE
if ($failExit -eq 0) {
    throw "Tampered bundle verification should have failed but returned 0.`n$failResult"
}
$failJson = $failResult | Out-String | ConvertFrom-Json
if ($failJson.status -ne "fail") {
    throw "Tampered bundle verification status is not fail.`n$failResult"
}
if (-not ($failJson.reasons | Where-Object { $_ -match "bundle_sha256 mismatch" })) {
    throw "Tampered bundle verification reasons do not mention bundle_sha256 mismatch.`n$failResult"
}

Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

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

Write-Host "V1.8 export bundle verify CLI release verification passed."
