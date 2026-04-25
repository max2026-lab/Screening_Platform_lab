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
        StdOut = $stdout.Trim()
        StdErr = $stderr.Trim()
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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase8-reproducibility-release-verify-" + [guid]::NewGuid().ToString())
$reproFlowRoot = Join-Path $baseTempRoot "repro"
$mismatchFlowRoot = Join-Path $baseTempRoot "date-mismatch"
New-Item -ItemType Directory -Path $reproFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $mismatchFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    # Flow A: same-input reproducibility smoke
    Set-Location $reproFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $reproFlowRoot "phase8-repro.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Flow A init-db failed.`n$($initResult.StdErr)"
    }

    $runA = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase8-repro-a-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    $null = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase8-repro-a-001")

    $runB = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase8-repro-b-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    $null = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase8-repro-b-001")

    $reproducibility = Invoke-LawfulJson -Arguments @(
        "reproducibility-check",
        "--run-id", "phase8-repro-a-001",
        "--comparison-run-id", "phase8-repro-b-001"
    )

    foreach ($field in @(
        "baseline_run_id",
        "comparison_run_id",
        "same_processing_baseline",
        "same_aoi_hash",
        "same_date_window",
        "same_source_scene_manifest_hash",
        "baseline_candidate_count",
        "comparison_candidate_count",
        "common_candidate_count",
        "added_candidate_ids",
        "removed_candidate_ids",
        "top10_stability_rate",
        "top10_stability_threshold",
        "rank_deltas",
        "score_deltas",
        "status",
        "reasons",
        "baseline_run",
        "comparison_run"
    )) {
        if (-not $reproducibility.PSObject.Properties[$field]) {
            throw "Flow A reproducibility-check missing field '$field'"
        }
    }

    if ($reproducibility.status -ne "pass") {
        throw "Flow A expected reproducibility status=pass, got $($reproducibility.status)"
    }
    if (-not $reproducibility.same_processing_baseline) {
        throw "Flow A expected same_processing_baseline=true"
    }
    if (-not $reproducibility.same_aoi_hash) {
        throw "Flow A expected same_aoi_hash=true"
    }
    if (-not $reproducibility.same_date_window) {
        throw "Flow A expected same_date_window=true"
    }
    if (-not $reproducibility.same_source_scene_manifest_hash) {
        throw "Flow A expected same_source_scene_manifest_hash=true"
    }
    if ([double]$reproducibility.top10_stability_rate -ne 1.0) {
        throw "Flow A expected top10_stability_rate=1.0, got $($reproducibility.top10_stability_rate)"
    }
    if (@($reproducibility.added_candidate_ids).Count -ne 0) {
        throw "Flow A expected added_candidate_ids to be empty"
    }
    if (@($reproducibility.removed_candidate_ids).Count -ne 0) {
        throw "Flow A expected removed_candidate_ids to be empty"
    }
    if ($null -eq $reproducibility.baseline_run.composite_quality) {
        throw "Flow A expected baseline_run.composite_quality"
    }
    if ($null -eq $reproducibility.comparison_run.composite_quality) {
        throw "Flow A expected comparison_run.composite_quality"
    }

    # Flow B: date-window mismatch should fail cleanly
    Set-Location $mismatchFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $reproFlowRoot "phase8-repro.sqlite3"

    $runC = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase8-repro-c-date-mismatch",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-02-01",
        "--end-date", "2024-03-31"
    )
    $null = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase8-repro-c-date-mismatch")

    $mismatchResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "reproducibility-check",
        "--run-id", "phase8-repro-a-001",
        "--comparison-run-id", "phase8-repro-c-date-mismatch"
    )
    if ($mismatchResult.ExitCode -eq 0) {
        throw "Flow B expected reproducibility-check to fail for date mismatch"
    }
    if ($mismatchResult.StdErr -match "Traceback") {
        throw "Flow B stderr unexpectedly contained a traceback.`n$($mismatchResult.StdErr)"
    }
    if (-not $mismatchResult.StdOut) {
        throw "Flow B expected JSON output on stdout"
    }
    $mismatchPayload = $mismatchResult.StdOut | ConvertFrom-Json
    if ($mismatchPayload.status -ne "fail") {
        throw "Flow B expected reproducibility status=fail, got $($mismatchPayload.status)"
    }
    if ($mismatchPayload.same_date_window -ne $false) {
        throw "Flow B expected same_date_window=false"
    }
    if (-not (($mismatchPayload.reasons | ForEach-Object { [string]$_ }) -match "Date window differs")) {
        throw "Flow B expected reasons to include 'Date window differs'"
    }

    # Outside-cwd safety checks
    if (Test-Path (Join-Path $reproFlowRoot "config")) {
        throw "Flow A copied config into outside working directory"
    }
    if (Test-Path (Join-Path $mismatchFlowRoot "config")) {
        throw "Flow B copied config into outside working directory"
    }
    if (Test-Path (Join-Path $reproFlowRoot "sitecustomize.py")) {
        throw "Flow A created sitecustomize.py in outside working directory"
    }
    if (Test-Path (Join-Path $mismatchFlowRoot "sitecustomize.py")) {
        throw "Flow B created sitecustomize.py in outside working directory"
    }
    if (Test-Path Env:PYTHONPATH) {
        throw "PYTHONPATH must not be set after verification flows"
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

Write-Host "Phase 8 reproducibility release verification passed."
