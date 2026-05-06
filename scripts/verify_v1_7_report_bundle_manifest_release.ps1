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

$pytestResult = & uv run pytest tests\integration\test_export_repository.py --tb=short
if ($LASTEXITCODE -ne 0) {
    throw "Targeted export repository tests failed.`n$pytestResult"
}

$exportRepoPath = Join-Path $repoRoot "src\lawful_anomaly_screening\db\repositories\export_repository.py"
$exportRepoText = Get-Content -Path $exportRepoPath -Raw
$requiredPatterns = @(
    'bundle_manifest_path',
    '_write_report_bundle_manifest',
    'v1\.7_report_bundle_manifest',
    'bundle_sha256',
    'bundle_members',
    'files'
)
foreach ($pattern in $requiredPatterns) {
    if ($exportRepoText -notmatch $pattern) {
        throw "export_repository.py missing required pattern: $pattern"
    }
}

$testPath = Join-Path $repoRoot "tests\integration\test_export_repository.py"
$testText = Get-Content -Path $testPath -Raw
$testPatterns = @(
    'bundle_manifest_path',
    'v1\.7_report_bundle_manifest',
    'bundle_sha256',
    'bundle_members',
    'zero_candidate',
    'non_report_audiences_do_not_create_bundles'
)
foreach ($pattern in $testPatterns) {
    if ($testText -notmatch $pattern) {
        throw "test_export_repository.py missing required pattern: $pattern"
    }
}

$tempDir = "C:\temp\screening-v1-7-report-bundle-manifest-release"
if (Test-Path $tempDir) {
    Remove-Item -Recurse -Force $tempDir
}
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$env:LAWFUL_ANOMALY_DB_PATH = "$tempDir\test.sqlite3"

$zeroBootstrap = @"
import sys
sys.path.insert(0, r'$repoRoot')
from pathlib import Path
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db

db_path = Path(r'$tempDir\test.sqlite3')
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_7_default',
    score_formula_version='v1.7.0-phase0',
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
if ($zeroJson.bundle_manifest_path -notmatch '\.manifest\.json$') {
    throw "bundle_manifest_path does not end with .manifest.json"
}
if ($zeroJson.exact_coordinates_included -ne $false) {
    throw "exact_coordinates_included should be false for restricted"
}
if (-not $zeroJson.audit_manifest) {
    throw "audit_manifest missing from export output"
}

$zeroReportPath = Join-Path $tempDir $zeroJson.artifact_path
$zeroBundlePath = Join-Path $tempDir $zeroJson.bundle_path
$zeroManifestPath = Join-Path $tempDir $zeroJson.bundle_manifest_path
if (-not (Test-Path $zeroReportPath)) {
    throw "Zero-candidate markdown report not found at $zeroReportPath"
}
if (-not (Test-Path $zeroBundlePath)) {
    throw "Zero-candidate ZIP bundle not found at $zeroBundlePath"
}
if (-not (Test-Path $zeroManifestPath)) {
    throw "Zero-candidate sidecar manifest not found at $zeroManifestPath"
}
if ((Split-Path -Leaf $zeroBundlePath) -ne $zeroJson.bundle_name) {
    throw "Zero-candidate bundle filename mismatch"
}
if ((Split-Path -Leaf $zeroManifestPath) -ne "$($zeroJson.bundle_name).manifest.json") {
    throw "Zero-candidate sidecar manifest filename mismatch"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$zipNames = $zip.Entries | ForEach-Object { $_.Name } | Sort-Object
$zip.Dispose()
$expectedNames = @($zeroJson.artifact_name, 'audit_manifest.json', 'SHA256SUMS.txt') | Sort-Object
if (($zipNames -join ',') -ne ($expectedNames -join ',')) {
    throw "Zero-candidate ZIP contents mismatch. Expected: $($expectedNames -join ', '), Got: $($zipNames -join ', ')"
}

$sidecar = Get-Content -Path $zeroManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sidecar.schema_version -ne "v1.7_report_bundle_manifest") {
    throw "sidecar schema_version mismatch"
}
if ($sidecar.run_id -ne $zeroJson.run_id) {
    throw "sidecar run_id mismatch"
}
if ($sidecar.export_record_id -ne $zeroJson.export_record_id) {
    throw "sidecar export_record_id mismatch"
}
if ($sidecar.audience -ne "report_pdf") {
    throw "sidecar audience mismatch"
}
if ($sidecar.precision_tier -ne "restricted") {
    throw "sidecar precision_tier mismatch"
}
if ($sidecar.exact_coordinates_included -ne $false) {
    throw "sidecar exact_coordinates_included mismatch"
}
if ($sidecar.artifact_name -ne $zeroJson.artifact_name) {
    throw "sidecar artifact_name mismatch"
}
if ($sidecar.artifact_path -ne $zeroJson.artifact_path) {
    throw "sidecar artifact_path mismatch"
}
if ($sidecar.bundle_name -ne $zeroJson.bundle_name) {
    throw "sidecar bundle_name mismatch"
}
if ($sidecar.bundle_path -ne $zeroJson.bundle_path) {
    throw "sidecar bundle_path mismatch"
}
$expectedBundleSha256 = (Get-FileHash -Path $zeroBundlePath -Algorithm SHA256).Hash.ToLower()
if ($sidecar.bundle_sha256 -ne $expectedBundleSha256) {
    throw "sidecar bundle_sha256 mismatch"
}
$expectedMembers = @($zeroJson.artifact_name, 'audit_manifest.json', 'SHA256SUMS.txt') | Sort-Object
if (($sidecar.bundle_members | Sort-Object) -join ',' -ne ($expectedMembers -join ',')) {
    throw "sidecar bundle_members mismatch"
}
if ($sidecar.audit_manifest_hash -ne $zeroJson.audit_manifest.audit_manifest_hash) {
    throw "sidecar audit_manifest_hash mismatch"
}
if ($sidecar.candidate_count -ne 0) {
    throw "sidecar candidate_count should be 0 for zero-candidate"
}
if ($sidecar.files.Count -ne 4) {
    throw "sidecar files should have exactly 4 entries"
}

$reportEntry = $sidecar.files | Where-Object { $_.kind -eq 'report_markdown' }
$bundleEntry = $sidecar.files | Where-Object { $_.kind -eq 'bundle_zip' }
$auditEntry = $sidecar.files | Where-Object { $_.kind -eq 'audit_manifest' }
$shaEntry = $sidecar.files | Where-Object { $_.kind -eq 'checksum_manifest' }
if (-not $reportEntry) { throw "sidecar missing report_markdown entry" }
if (-not $bundleEntry) { throw "sidecar missing bundle_zip entry" }
if (-not $auditEntry) { throw "sidecar missing audit_manifest entry" }
if (-not $shaEntry) { throw "sidecar missing checksum_manifest entry" }

$reportHash = (Get-FileHash -Path $zeroReportPath -Algorithm SHA256).Hash.ToLower()
if ($reportEntry.sha256 -ne $reportHash) {
    throw "sidecar report_markdown sha256 mismatch"
}
if ($bundleEntry.sha256 -ne $expectedBundleSha256) {
    throw "sidecar bundle_zip sha256 mismatch"
}

$zip = [System.IO.Compression.ZipFile]::OpenRead($zeroBundlePath)
$auditStream = $zip.GetEntry('audit_manifest.json').Open()
$auditReader = New-Object System.IO.StreamReader($auditStream)
$auditText = $auditReader.ReadToEnd()
$auditReader.Close()
$shaStream = $zip.GetEntry('SHA256SUMS.txt').Open()
$shaReader = New-Object System.IO.StreamReader($shaStream)
$shaText = $shaReader.ReadToEnd()
$shaReader.Close()
$zip.Dispose()

$auditHash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($auditText))).Replace("-", "").ToLower()
$shaHash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($shaText))).Replace("-", "").ToLower()

if ($auditEntry.sha256 -ne $auditHash) {
    throw "sidecar audit_manifest sha256 mismatch"
}
if ($shaEntry.sha256 -ne $shaHash) {
    throw "sidecar checksum_manifest sha256 mismatch"
}

$sidecarText = Get-Content -Path $zeroManifestPath -Raw -Encoding UTF8
# Check for forbidden geometry keys as standalone JSON keys (with quotes)
$forbiddenKeys = @('"centroid"', '"clipped_geometry"', '"bounds"', '"coordinates"')
foreach ($key in $forbiddenKeys) {
    if ($sidecarText -match $key) {
        throw "sidecar manifest contains forbidden key: $key"
    }
}

$nonReportTest = @"
import sys
sys.path.insert(0, r'$repoRoot')
from pathlib import Path
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db
from lawful_anomaly_screening.db.repositories.export_repository import ExportRepository

db_path = Path(r'$tempDir\non_report.sqlite3')
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_7_default',
    score_formula_version='v1.7.0-phase0',
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
public_record = repo.persist_export(run_id='run-002', audience='public', candidates=candidates)
reviewer_record = repo.persist_export(run_id='run-002', audience='reviewer', candidates=candidates)
field_record = repo.persist_export(run_id='run-002', audience='field', candidates=candidates)
assert public_record['bundle_manifest_path'] is None, 'public should have no bundle_manifest_path'
assert reviewer_record['bundle_manifest_path'] is None, 'reviewer should have no bundle_manifest_path'
assert field_record['bundle_manifest_path'] is None, 'field should have no bundle_manifest_path'
print('NON_REPORT_OK')
"@

$nonReportResult = & uv run python -c $nonReportTest
if ($LASTEXITCODE -ne 0) {
    throw "Non-report sidecar test failed.`n$nonReportResult"
}
if ($nonReportResult -notmatch 'NON_REPORT_OK') {
    throw "Non-report sidecar test did not complete successfully.`n$nonReportResult"
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

Write-Host "V1.7 report bundle manifest release verification passed."
