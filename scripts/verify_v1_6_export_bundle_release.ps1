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
$pytestResult = & uv run pytest tests\integration\test_export_repository.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted export repository tests failed.`n$pytestResult"
}

# Verify source code contains bundle implementation
$exportRepoPath = Join-Path $repoRoot "src\lawful_anomaly_screening\db\repositories\export_repository.py"
$exportRepoText = Get-Content -Path $exportRepoPath -Raw
$requiredPatterns = @(
    'bundle_path',
    '_write_report_bundle',
    'audit_manifest\.json',
    'SHA256SUMS\.txt',
    'zipfile'
)
foreach ($pattern in $requiredPatterns) {
    if ($exportRepoText -notmatch $pattern) {
        throw "export_repository.py missing required pattern: $pattern"
    }
}

# Verify tests contain bundle assertions
$testPath = Join-Path $repoRoot "tests\integration\test_export_repository.py"
$testText = Get-Content -Path $testPath -Raw
$testPatterns = @(
    'bundle_path',
    'audit_manifest\.json',
    'SHA256SUMS\.txt',
    'zero_candidate',
    'non_report_audiences_do_not_create_bundles'
)
foreach ($pattern in $testPatterns) {
    if ($testText -notmatch $pattern) {
        throw "test_export_repository.py missing required pattern: $pattern"
    }
}

# CLI smoke test with temp DB
$tempDir = "C:\temp\screening-v1-6-export-bundle-release"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$env:LAWFUL_ANOMALY_DB_PATH = "$tempDir\test.sqlite3"

# Zero-candidate CLI smoke (no complex FK chain needed)
$zeroBootstrap = @"
import sys
sys.path.insert(0, r'$repoRoot')
from pathlib import Path
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db

db_path = Path(r'$tempDir\test.sqlite3')
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_6_default',
    score_formula_version='v1.6.0-phase0',
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
print('ZERO_BOOTSTRAP_OK')
"@

$zeroResult = & uv run python -c $zeroBootstrap
if ($LASTEXITCODE -ne 0) {
    throw "Zero-candidate DB bootstrap failed.`n$zeroResult"
}

Push-Location $tempDir
$zeroExportResult = & lawful-anomaly export-create --run-id run-001 --audience report_pdf --requested-precision restricted 2>&1
Pop-Location
$zeroExit = $LASTEXITCODE
if ($zeroExit -ne 0) {
    throw "Zero-candidate export-create failed with exit $zeroExit.`n$zeroExportResult"
}
$zeroJson = $zeroExportResult | Out-String | ConvertFrom-Json
if ($zeroJson.artifact_path -notmatch '\.md$') {
    throw "artifact_path does not end with .md"
}
if ($zeroJson.bundle_name -notmatch '\.zip$') {
    throw "bundle_name does not end with .zip"
}
if ($zeroJson.bundle_path -notmatch '\.zip$') {
    throw "bundle_path does not end with .zip"
}
if ($zeroJson.exact_coordinates_included -ne $false) {
    throw "exact_coordinates_included should be false for restricted"
}
if (-not $zeroJson.audit_manifest) {
    throw "audit_manifest missing from export output"
}

# Verify zero-candidate files exist
$zeroReportPath = Join-Path $tempDir $zeroJson.artifact_path
$zeroBundlePath = Join-Path $tempDir $zeroJson.bundle_path
if (-not (Test-Path $zeroReportPath)) {
    throw "Zero-candidate markdown report not found at $zeroReportPath"
}
if (-not (Test-Path $zeroBundlePath)) {
    throw "Zero-candidate ZIP bundle not found at $zeroBundlePath"
}
if ((Split-Path -Leaf $zeroBundlePath) -ne $zeroJson.bundle_name) {
    throw "Zero-candidate bundle filename mismatch"
}

# Verify zero-candidate ZIP contents
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$zipNames = $zip.Entries | ForEach-Object { $_.Name } | Sort-Object
$zip.Dispose()
$expectedNames = @($zeroJson.artifact_name, 'audit_manifest.json', 'SHA256SUMS.txt') | Sort-Object
if (($zipNames -join ',') -ne ($expectedNames -join ',')) {
    throw "Zero-candidate ZIP contents mismatch. Expected: $($expectedNames -join ', '), Got: $($zipNames -join ', ')"
}

# Verify zero-candidate audit_manifest.json inside ZIP
$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$manifestEntry = $zip.GetEntry('audit_manifest.json')
$manifestReader = New-Object System.IO.StreamReader($manifestEntry.Open())
$manifestText = $manifestReader.ReadToEnd()
$manifestReader.Close()
$zip.Dispose()
$manifestInside = $manifestText | ConvertFrom-Json
# Compare key fields instead of full JSON string to avoid serialization diffs
if ($manifestInside.export_record_id -ne $zeroJson.audit_manifest.export_record_id) {
    throw "audit_manifest export_record_id mismatch"
}
if ($manifestInside.run_id -ne $zeroJson.audit_manifest.run_id) {
    throw "audit_manifest run_id mismatch"
}
if ($manifestInside.precision_tier -ne $zeroJson.audit_manifest.precision_tier) {
    throw "audit_manifest precision_tier mismatch"
}
if ($manifestInside.candidate_count -ne $zeroJson.audit_manifest.candidate_count) {
    throw "audit_manifest candidate_count mismatch"
}
if ($manifestInside.audit_manifest_hash -ne $zeroJson.audit_manifest.audit_manifest_hash) {
    throw "audit_manifest hash mismatch"
}

# Verify zero-candidate SHA256SUMS.txt inside ZIP
$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$shaEntry = $zip.GetEntry('SHA256SUMS.txt')
$shaReader = New-Object System.IO.StreamReader($shaEntry.Open())
$shaText = $shaReader.ReadToEnd()
$shaReader.Close()
$zip.Dispose()
if ($shaText -notmatch [regex]::Escape($zeroJson.artifact_name)) {
    throw "Zero-candidate SHA256SUMS.txt missing artifact entry"
}
if ($shaText -notmatch 'audit_manifest\.json') {
    throw "Zero-candidate SHA256SUMS.txt missing audit_manifest.json entry"
}

# Verify zero-candidate report content inside ZIP matches file on disk
$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$reportEntry = $zip.GetEntry($zeroJson.artifact_name)
$reportReader = New-Object System.IO.StreamReader($reportEntry.Open())
$reportInside = $reportReader.ReadToEnd()
$reportReader.Close()
$zip.Dispose()
$reportDisk = Get-Content -Path $zeroReportPath -Raw -Encoding UTF8
if ($reportInside -ne $reportDisk) {
    throw "Zero-candidate report inside ZIP does not match file on disk"
}

# Verify no exact coordinates in zero-candidate restricted report
if ($reportDisk -match 'centroid') {
    throw "Zero-candidate restricted report should not contain centroid"
}

# With-candidate bundle test via Python API (avoids complex CLI FK setup)
$apiTestScript = @"
import sys
sys.path.insert(0, r'$repoRoot')
from pathlib import Path
import json
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository

db_path = Path(r'$tempDir\api.sqlite3')
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_6_default',
    score_formula_version='v1.6.0-phase0',
    source_scene_manifest_hash='manifest-hash-002',
    source_endpoint_id='earth_search',
    run_id='run-002',
    manifest_path='data/manifests/manifest-hash-002.json',
)
repo = ExportRepository(db_path, export_root=db_path.parent)
candidates = [
    {
        'candidate_id': 'candidate-001',
        'centroid': [1234.0, 2789.0],
        'bounds': [1201.0, 2705.0, 1281.0, 2879.0],
        'area_m2': 9600.0,
        'possible_duplicate': False,
    },
]
result = repo.persist_export(
    run_id='run-002',
    audience='report_pdf',
    requested_precision='restricted',
    candidates=candidates,
)
assert result['bundle_path'] is not None, 'bundle_path missing'
assert result['bundle_path'].endswith('.zip'), 'bundle_path not .zip'
bundle_path = db_path.parent / result['bundle_path']
assert bundle_path.exists(), 'bundle does not exist'
assert bundle_path.name == result['bundle_name'], 'bundle name mismatch'
import zipfile
with zipfile.ZipFile(bundle_path, 'r') as zf:
    names = sorted(zf.namelist())
    expected = sorted([result['artifact_name'], 'audit_manifest.json', 'SHA256SUMS.txt'])
    assert names == expected, f'ZIP contents mismatch: {names} != {expected}'
print('API_BUNDLE_OK')
"@

$apiResult = & uv run python -c $apiTestScript
if ($LASTEXITCODE -ne 0) {
    throw "API bundle test failed.`n$apiResult"
}
if ($apiResult -notmatch 'API_BUNDLE_OK') {
    throw "API bundle test did not complete successfully.`n$apiResult"
}

# Cleanup
Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

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

Write-Host "V1.6 export bundle release verification passed."
