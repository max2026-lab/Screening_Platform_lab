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

$venvPython = Join-Path (Split-Path -Parent $repoLocalCliPath) "python.exe"
if (-not (Test-Path $venvPython)) {
    throw "venv python not found at $venvPython"
}

function Invoke-ProcessCapture {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = [string]::Join(
        " ",
        ($Arguments | ForEach-Object {
            if ($_ -match '[\s"]') {
                '"' + ($_ -replace '"', '\"') + '"'
            }
            else {
                $_
            }
        })
    )
    $startInfo.WorkingDirectory = (Get-Location).Path
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return [pscustomobject]@{
        ExitCode = $process.ExitCode
        StdOut   = $stdout.Trim()
        StdErr   = $stderr.Trim()
    }
}

function Invoke-LawfulJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )
    $result = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments $Arguments
    if ($result.ExitCode -ne 0) {
        $details = if ($result.StdErr) { $result.StdErr } else { $result.StdOut }
        throw "lawful-anomaly $($Arguments -join ' ') failed.`n$details"
    }
    if (-not $result.StdOut) {
        throw "lawful-anomaly $($Arguments -join ' ') returned empty output"
    }
    return ($result.StdOut | ConvertFrom-Json)
}

function Bootstrap-ZeroCandidateRun {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DbPath,
        [Parameter(Mandatory = $true)]
        [string] $RunId
    )
    $bootstrapScript = @"
import sys
from lawful_anomaly_screening.db.sqlite import bootstrap_minimal_run, init_db

db_path = r'$DbPath'
run_id = r'$RunId'
init_db(db_path)
bootstrap_minimal_run(
    db_path,
    processing_baseline_id='baseline_v1_5_default',
    score_formula_version='v1.5.1-phase0',
    source_scene_manifest_hash='manifest-hash-zero',
    source_endpoint_id='earth_search',
    run_id=run_id,
    manifest_path='data/manifests/manifest-hash-zero.json',
    run_status='completed',
    aoi_hash='aoi-hash-zero',
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
"@
    $bootstrapResult = Invoke-ProcessCapture -FilePath $venvPython -Arguments @("-c", $bootstrapScript)
    if ($bootstrapResult.ExitCode -ne 0) {
        throw "Bootstrap zero-candidate run failed.`n$($bootstrapResult.StdErr)"
    }
}

$baseTempRoot = Join-Path $env:TEMP ("v1_1-no-candidates-export-verify-" + [guid]::NewGuid().ToString())
$knownCandidateRoot = Join-Path $baseTempRoot "known-candidate"
$zeroCandidateRoot = Join-Path $baseTempRoot "zero-candidate"
$unsupportedRoot = Join-Path $baseTempRoot "unsupported-audience"
New-Item -ItemType Directory -Path $knownCandidateRoot -Force | Out-Null
New-Item -ItemType Directory -Path $zeroCandidateRoot -Force | Out-Null
New-Item -ItemType Directory -Path $unsupportedRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$zeroCandidateAoi = Join-Path $zeroCandidateRoot "zero_candidate_aoi.geojson"
@'
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[0.0,0.0],[0.0001,0.0],[0.0001,0.0001],[0.0,0.0001],[0.0,0.0]]]}}]}
'@ | Set-Content -LiteralPath $zeroCandidateAoi -Encoding UTF8 -NoNewline

$unsupportedAoi = Join-Path $unsupportedRoot "unsupported_aoi.geojson"
@'
{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[0.0,0.0],[0.0001,0.0],[0.0001,0.0001],[0.0,0.0001],[0.0,0.0]]]}}]}
'@ | Set-Content -LiteralPath $unsupportedAoi -Encoding UTF8 -NoNewline

$originalLocation = Get-Location
try {
    # --- Known-candidate flow ---
    Set-Location $knownCandidateRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $knownCandidateRoot "known-candidate.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Known-candidate init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "known-candidate-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($createRun.legal_gate.decision -ne "pass") {
        throw "Known-candidate create-run expected legal_gate.decision=pass"
    }

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "known-candidate-001")
    if ([int]$executeRun.candidate_count -le 0) {
        throw "Known-candidate execute-run expected candidate_count > 0, got $($executeRun.candidate_count)"
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "known-candidate-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if ($exportCreate.exact_coordinates_included -ne $false) {
        throw "Known-candidate restricted report expected exact_coordinates_included=false"
    }
    $reportPath = Join-Path $knownCandidateRoot $exportCreate.artifact_path
    if (-not (Test-Path $reportPath)) {
        throw "Known-candidate report markdown not found at $reportPath"
    }
    $reportText = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8
    if ($reportText -notmatch 'Candidate count: `[1-9]') {
        throw "Known-candidate report expected Candidate count greater than 0"
    }

    # --- Zero-candidate flow ---
    Set-Location $zeroCandidateRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $zeroCandidateRoot "zero-candidate.sqlite3"

    Bootstrap-ZeroCandidateRun -DbPath $env:LAWFUL_ANOMALY_DB_PATH -RunId "zero-candidate-001"

    $exportZero = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "zero-candidate-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if (-not ($exportZero.candidates -is [array] -and $exportZero.candidates.Count -eq 0)) {
        throw "Zero-candidate export expected candidates == []"
    }
    if (-not $exportZero.audit_manifest) {
        throw "Zero-candidate export expected audit_manifest"
    }
    if (-not ($exportZero.artifact_path -match "\.md$")) {
        throw "Zero-candidate export expected artifact_path to end with .md"
    }
    if ($exportZero.exact_coordinates_included -ne $false) {
        throw "Zero-candidate export expected exact_coordinates_included=false"
    }

    $zeroReportPath = Join-Path $zeroCandidateRoot $exportZero.artifact_path
    if (-not (Test-Path $zeroReportPath)) {
        throw "Zero-candidate report markdown not found at $zeroReportPath"
    }
    $zeroReportText = Get-Content -LiteralPath $zeroReportPath -Raw -Encoding UTF8
    foreach ($expectedFragment in @(
        'Candidate count: `0`',
        '## No Exportable Candidates Found',
        'This AOI/date window was screened and produced zero exportable candidates.'
    )) {
        if ($zeroReportText -notmatch [regex]::Escape($expectedFragment)) {
            throw "Zero-candidate report missing expected text: $expectedFragment"
        }
    }
    if ($zeroReportText -match "centroid") {
        throw "Zero-candidate report must not include exact candidate coordinates"
    }
    if ($zeroReportText -notmatch "Legal gate decision:") {
        throw "Zero-candidate report expected legal gate decision"
    }
    if ($zeroReportText -notmatch "Start date:") {
        throw "Zero-candidate report expected start date"
    }
    if ($zeroReportText -notmatch "End date:") {
        throw "Zero-candidate report expected end date"
    }

    # --- Unsupported audience flow ---
    Set-Location $unsupportedRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $unsupportedRoot "unsupported-audience.sqlite3"

    Bootstrap-ZeroCandidateRun -DbPath $env:LAWFUL_ANOMALY_DB_PATH -RunId "unsupported-audience-001"

    $unsupportedResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "export-create",
        "--run-id", "unsupported-audience-001",
        "--audience", "public"
    )
    if ($unsupportedResult.ExitCode -eq 0) {
        throw "Unsupported audience export expected non-zero exit, got 0"
    }
    if ($unsupportedResult.StdErr -notmatch "no export candidates found for run:") {
        throw "Unsupported audience export expected stderr containing 'no export candidates found for run:'"
    }
    $publicExportDir = Join-Path $unsupportedRoot "exports\public"
    if (Test-Path $publicExportDir) {
        $publicArtifacts = Get-ChildItem -Path $publicExportDir -Recurse -ErrorAction SilentlyContinue
        if ($publicArtifacts) {
            throw "Unsupported audience export must not create public export artifacts"
        }
    }

    # Outside-cwd safety checks
    foreach ($flowRoot in @($knownCandidateRoot, $zeroCandidateRoot, $unsupportedRoot)) {
        if (Test-Path (Join-Path $flowRoot "config")) {
            throw "Flow copied config into outside working directory: $flowRoot"
        }
        if (Test-Path (Join-Path $flowRoot "sitecustomize.py")) {
            throw "Flow created sitecustomize.py in outside working directory: $flowRoot"
        }
    }

    # Final repo cleanliness check
    Set-Location $repoRoot
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
}
finally {
    Set-Location $originalLocation
}

Write-Host "V1.1 no-candidates export report release verification passed."
