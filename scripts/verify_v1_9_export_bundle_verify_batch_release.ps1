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

$pytestResult = & uv run pytest tests\integration\test_export_bundle_verify_batch_cli.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted export bundle verify batch CLI tests failed.`n$pytestResult"
}

$cliPath = Join-Path $repoRoot "src\lawful_anomaly_screening\cli.py"
$cliText = Get-Content -Path $cliPath -Raw
if ($cliText -notmatch 'export-bundle-verify-batch') {
    throw "cli.py missing export-bundle-verify-batch command"
}

$verifierPath = Join-Path $repoRoot "src\lawful_anomaly_screening\exports\bundle_verifier.py"
if (-not (Test-Path $verifierPath)) {
    throw "bundle_verifier.py not found"
}
$verifierText = Get-Content -Path $verifierPath -Raw
$verifierPatterns = @(
    'verify_export_bundle_batch',
    'discover_bundle_manifests',
    'load_manifest_list',
    'render_bundle_verify_batch_markdown',
    'verify_export_bundle'
)
foreach ($pattern in $verifierPatterns) {
    if ($verifierText -notmatch $pattern) {
        throw "bundle_verifier.py missing required pattern: $pattern"
    }
}

$tempDir = "C:\temp\screening-v1-9-export-bundle-verify-batch-release"
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
for run_id in ['run-001', 'run-002']:
    bootstrap_minimal_run(
        db_path,
        processing_baseline_id='baseline_v1_9_default',
        score_formula_version='v1.9.0-phase0',
        source_scene_manifest_hash=f'manifest-hash-{run_id}',
        source_endpoint_id='earth_search',
        run_id=run_id,
        manifest_path=f'data/manifests/manifest-hash-{run_id}.json',
        run_status='completed',
        aoi_hash=f'aoi-hash-{run_id}',
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
$exportResult1 = & lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted 2>&1
$exportResult2 = & lawful-anomaly export-create --run-id run-002 --audience report_pdf --requested-precision restricted 2>&1
Pop-Location
if ($LASTEXITCODE -ne 0) {
    throw "export-create failed.`n$exportResult1`n$exportResult2"
}

# Folder mode
Push-Location $tempDir
$batchResult = & lawful-anomaly export-bundle-verify-batch --reports-dir exports/reports --export-root . 2>&1
Pop-Location
$batchExit = $LASTEXITCODE
if ($batchExit -ne 0) {
    throw "export-bundle-verify-batch folder mode failed with exit $batchExit.`n$batchResult"
}
$batchJson = $batchResult | Out-String | ConvertFrom-Json
if ($batchJson.status -ne "pass") {
    throw "export-bundle-verify-batch folder mode status is not pass.`n$batchResult"
}
if ($batchJson.manifest_count -ne 2) {
    throw "manifest_count expected 2, got $($batchJson.manifest_count)"
}
if ($batchJson.passed_count -ne 2) {
    throw "passed_count expected 2, got $($batchJson.passed_count)"
}
if ($batchJson.failed_count -ne 0) {
    throw "failed_count expected 0, got $($batchJson.failed_count)"
}
foreach ($r in $batchJson.results) {
    if ($r.status -ne "pass") {
        throw "Nested result status is not pass.`n$($r | ConvertTo-Json)"
    }
}

# Manifest-list mode
$sidecarPaths = Get-ChildItem -Path "$tempDir\exports\reports" -Filter "*.zip.manifest.json" | Select-Object -ExpandProperty FullName
$manifestListPath = "$tempDir\manifest-list.txt"
$listContent = @(
    ""
    "# comment"
    ($sidecarPaths[0] -replace [regex]::Escape($tempDir + '\'), '')
    ""
    ($sidecarPaths[1] -replace [regex]::Escape($tempDir + '\'), '')
) -join "`n"
[System.IO.File]::WriteAllText($manifestListPath, $listContent, [System.Text.UTF8Encoding]::new($false))

Push-Location $tempDir
$listResult = & lawful-anomaly export-bundle-verify-batch --manifest-list manifest-list.txt --export-root . 2>&1
Pop-Location
$listExit = $LASTEXITCODE
if ($listExit -ne 0) {
    throw "export-bundle-verify-batch manifest-list mode failed with exit $listExit.`n$listResult"
}
$listJson = $listResult | Out-String | ConvertFrom-Json
if ($listJson.status -ne "pass") {
    throw "export-bundle-verify-batch manifest-list mode status is not pass.`n$listResult"
}
if ($listJson.manifest_count -ne 2) {
    throw "manifest-list mode manifest_count expected 2, got $($listJson.manifest_count)"
}

# No DB regression
$env:LAWFUL_ANOMALY_DB_PATH = "$tempDir\nonexistent.sqlite3"
Push-Location $tempDir
$noDbResult = & lawful-anomaly export-bundle-verify-batch --reports-dir exports/reports --export-root . 2>&1
Pop-Location
$noDbExit = $LASTEXITCODE
if ($noDbExit -ne 0) {
    throw "export-bundle-verify-batch with nonexistent DB failed with exit $noDbExit.`n$noDbResult"
}
$noDbJson = $noDbResult | Out-String | ConvertFrom-Json
if ($noDbJson.status -ne "pass") {
    throw "export-bundle-verify-batch with nonexistent DB status is not pass.`n$noDbResult"
}
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

# Negative smoke: tamper one sidecar
$sidecars = Get-ChildItem -Path "$tempDir\exports\reports" -Filter "*.zip.manifest.json"
$tamperedSidecar = $sidecars[0]
$sidecarContent = Get-Content -Path $tamperedSidecar.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
$sidecarContent.bundle_sha256 = "0" * 64
$sidecarContent | ConvertTo-Json -Depth 10 -Compress | Out-File -FilePath $tamperedSidecar.FullName -Encoding utf8 -NoNewline

Push-Location $tempDir
$failResult = & lawful-anomaly export-bundle-verify-batch --reports-dir exports/reports --export-root . 2>&1
Pop-Location
$failExit = $LASTEXITCODE
if ($failExit -eq 0) {
    throw "Tampered batch verification should have failed but returned 0.`n$failResult"
}
$failJson = $failResult | Out-String | ConvertFrom-Json
if ($failJson.status -ne "fail") {
    throw "Tampered batch verification status is not fail.`n$failResult"
}
if ($failJson.failed_count -ne 1) {
    throw "Tampered batch verification failed_count expected 1, got $($failJson.failed_count)"
}
if (-not ($failJson.reasons | Where-Object { $_ -match "bundle verification failed" })) {
    throw "Tampered batch verification reasons do not mention failed bundle.`n$failResult"
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

Write-Host "V1.9 export bundle verify batch release verification passed."
