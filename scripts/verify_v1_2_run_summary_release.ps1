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

function Write-GeoJsonNoBom {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,
        [Parameter(Mandatory = $true)]
        [string] $Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$baseTempRoot = Join-Path $env:TEMP ("v1_2-run-summary-verify-" + [guid]::NewGuid().ToString())
$knownCandidateRoot = Join-Path $baseTempRoot "known-candidate"
$zeroCandidateRoot = Join-Path $baseTempRoot "zero-candidate"
New-Item -ItemType Directory -Path $knownCandidateRoot -Force | Out-Null
New-Item -ItemType Directory -Path $zeroCandidateRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$zeroAoiJson = @'
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {},
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [35.1, 31.1],
            [35.12, 31.1],
            [35.12, 31.12],
            [35.1, 31.12],
            [35.1, 31.1]
          ]
        ]
      }
    }
  ]
}
'@

$zeroCandidateAoi = Join-Path $zeroCandidateRoot "zero_candidate_aoi.geojson"
Write-GeoJsonNoBom -Path $zeroCandidateAoi -Content $zeroAoiJson

$originalLocation = Get-Location
try {
    # --- Candidate-backed run summary ---
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
        "--run-id", "v12-known-candidate-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($createRun.legal_gate.decision -ne "pass") {
        throw "Known-candidate create-run expected legal_gate.decision=pass"
    }

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "v12-known-candidate-001")
    if ([int]$executeRun.candidate_count -le 0) {
        throw "Known-candidate execute-run expected candidate_count > 0, got $($executeRun.candidate_count)"
    }
    if (-not $executeRun.top_candidate_id) {
        throw "Known-candidate execute-run expected top_candidate_id not null"
    }

    $summaryResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("run-summary", "--run-id", "v12-known-candidate-001")
    if ($summaryResult.ExitCode -ne 0) {
        throw "Known-candidate run-summary failed.`n$($summaryResult.StdErr)"
    }
    $summary = $summaryResult.StdOut | ConvertFrom-Json
    if ([int]$summary.candidate_count -le 0) {
        throw "Known-candidate run-summary expected candidate_count > 0, got $($summary.candidate_count)"
    }
    if (-not $summary.top_candidate_id) {
        throw "Known-candidate run-summary expected top_candidate_id not null"
    }
    if ($summary.status -notin @("review_ready", "completed")) {
        throw "Known-candidate run-summary expected status review_ready or completed, got $($summary.status)"
    }
    if (-not $summary.source_endpoint_id) {
        throw "Known-candidate run-summary expected source_endpoint_id"
    }
    if (-not $summary.source_scene_manifest_hash) {
        throw "Known-candidate run-summary expected source_scene_manifest_hash"
    }
    if ([int]$summary.tile_count -le 0) {
        throw "Known-candidate run-summary expected tile_count > 0, got $($summary.tile_count)"
    }
    if ([int]$summary.selected_tile_count -le 0) {
        throw "Known-candidate run-summary expected selected_tile_count > 0, got $($summary.selected_tile_count)"
    }

    # --- Zero-candidate run summary ---
    Set-Location $zeroCandidateRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $zeroCandidateRoot "zero-candidate.sqlite3"

    $zeroInitResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($zeroInitResult.ExitCode -ne 0) {
        throw "Zero-candidate init-db failed.`n$($zeroInitResult.StdErr)"
    }

    $zeroCreateRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "v12-zero-candidate-001",
        "--aoi-path", $zeroCandidateAoi,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($zeroCreateRun.legal_gate.decision -ne "pass") {
        throw "Zero-candidate create-run expected legal_gate.decision=pass"
    }

    $zeroExecuteRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "v12-zero-candidate-001")
    if ([int]$zeroExecuteRun.candidate_count -ne 0) {
        throw "Zero-candidate execute-run expected candidate_count = 0, got $($zeroExecuteRun.candidate_count)"
    }

    $zeroSummaryResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("run-summary", "--run-id", "v12-zero-candidate-001")
    if ($zeroSummaryResult.ExitCode -ne 0) {
        throw "Zero-candidate run-summary failed.`n$($zeroSummaryResult.StdErr)"
    }
    $zeroSummary = $zeroSummaryResult.StdOut | ConvertFrom-Json
    if ([int]$zeroSummary.candidate_count -ne 0) {
        throw "Zero-candidate run-summary expected candidate_count = 0, got $($zeroSummary.candidate_count)"
    }
    if ($null -ne $zeroSummary.top_candidate_id) {
        throw "Zero-candidate run-summary expected top_candidate_id null, got $($zeroSummary.top_candidate_id)"
    }
    if ($zeroSummary.status -notin @("review_ready", "completed")) {
        throw "Zero-candidate run-summary expected status review_ready or completed, got $($zeroSummary.status)"
    }
    if (-not $zeroSummary.source_endpoint_id) {
        throw "Zero-candidate run-summary expected source_endpoint_id"
    }
    if (-not $zeroSummary.source_scene_manifest_hash) {
        throw "Zero-candidate run-summary expected source_scene_manifest_hash"
    }
    if ($null -eq $zeroSummary.tile_count) {
        throw "Zero-candidate run-summary expected tile_count"
    }
    if ($null -eq $zeroSummary.selected_tile_count) {
        throw "Zero-candidate run-summary expected selected_tile_count"
    }

    # --- Latest export fields ---
    $exportResult = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "v12-zero-candidate-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if (-not $exportResult.artifact_path) {
        throw "Zero-candidate export expected artifact_path"
    }

    $summaryWithExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("run-summary", "--run-id", "v12-zero-candidate-001")
    if ($summaryWithExportResult.ExitCode -ne 0) {
        throw "Zero-candidate run-summary after export failed.`n$($summaryWithExportResult.StdErr)"
    }
    $summaryWithExport = $summaryWithExportResult.StdOut | ConvertFrom-Json
    if (-not $summaryWithExport.latest_export_record_id) {
        throw "Zero-candidate run-summary expected latest_export_record_id after export"
    }
    if (-not $summaryWithExport.latest_export_artifact_path) {
        throw "Zero-candidate run-summary expected latest_export_artifact_path after export"
    }
    $artifactFullPath = Join-Path $zeroCandidateRoot $summaryWithExport.latest_export_artifact_path
    if (-not (Test-Path $artifactFullPath)) {
        throw "Zero-candidate export artifact not found at $artifactFullPath"
    }

    # --- Missing run failure ---
    $missingResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("run-summary", "--run-id", "missing-run")
    if ($missingResult.ExitCode -eq 0) {
        throw "Missing run run-summary expected non-zero exit, got 0"
    }
    if ($missingResult.StdErr -notmatch "run not found: missing-run") {
        throw "Missing run run-summary expected stderr containing 'run not found: missing-run'"
    }

    # Outside-cwd safety checks
    foreach ($flowRoot in @($knownCandidateRoot, $zeroCandidateRoot)) {
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

Write-Host "V1.2 run-summary release verification passed."
