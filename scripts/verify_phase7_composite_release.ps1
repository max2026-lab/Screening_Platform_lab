#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$currentDir = (Resolve-Path ".").Path
if ($currentDir -ne $repoRoot) {
    throw "Run this script from repo root: $repoRoot"
}

if (-not (Get-Command lawful-anomaly -ErrorAction SilentlyContinue)) {
    throw "Required command not found: lawful-anomaly. Install the package first (for example, `uv tool install C:\Dev\Screening_Platform_lab`)."
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

function Assert-CompositeQualityShape {
    param(
        [Parameter(Mandatory = $true)]
        [object] $CompositeQuality,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if ($null -eq $CompositeQuality) {
        throw "$Context missing composite_quality"
    }

    foreach ($field in @(
        "scene_count",
        "contributing_scene_ids",
        "mean_cloud_cover",
        "max_cloud_cover",
        "clear_scene_count",
        "cloudy_scene_count",
        "cloud_policy_decision",
        "cloud_policy_reason"
    )) {
        if (-not $CompositeQuality.PSObject.Properties[$field]) {
            throw "$Context composite_quality missing field '$field'"
        }
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase7-composite-release-verify-" + [guid]::NewGuid().ToString())
$normalFlowRoot = Join-Path $baseTempRoot "normal"
$failFlowRoot = Join-Path $baseTempRoot "cloud-policy-fail"
New-Item -ItemType Directory -Path $normalFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $failFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    # Flow A: normal allowed path smoke
    Set-Location $normalFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $normalFlowRoot "phase7-normal.sqlite3"

    $normalInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($normalInit.ExitCode -ne 0) {
        throw "Flow A init-db failed.`n$($normalInit.StdErr)"
    }

    $normalCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase7-normal-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($normalCreate.legal_gate.decision -ne "pass") {
        throw "Flow A create-run expected legal_gate.decision=pass, got $($normalCreate.legal_gate.decision)"
    }

    $normalExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase7-normal-001")
    if (-not $normalExecute.PSObject.Properties["composite_quality"]) {
        throw "Flow A execute-run missing top-level composite_quality"
    }
    if (-not $normalExecute.run_metadata.PSObject.Properties["composite_quality"]) {
        throw "Flow A execute-run missing run_metadata.composite_quality"
    }
    if (-not $normalExecute.scene_summary.PSObject.Properties["composite_quality"]) {
        throw "Flow A execute-run missing scene_summary.composite_quality"
    }

    Assert-CompositeQualityShape -CompositeQuality $normalExecute.composite_quality -Context "Flow A top-level"
    Assert-CompositeQualityShape -CompositeQuality $normalExecute.run_metadata.composite_quality -Context "Flow A run_metadata"
    Assert-CompositeQualityShape -CompositeQuality $normalExecute.scene_summary.composite_quality -Context "Flow A scene_summary"

    $topCompositeJson = $normalExecute.composite_quality | ConvertTo-Json -Depth 10 -Compress
    $runCompositeJson = $normalExecute.run_metadata.composite_quality | ConvertTo-Json -Depth 10 -Compress
    $sceneCompositeJson = $normalExecute.scene_summary.composite_quality | ConvertTo-Json -Depth 10 -Compress
    if ($topCompositeJson -ne $runCompositeJson -or $topCompositeJson -ne $sceneCompositeJson) {
        throw "Flow A composite_quality objects expected to be identical across execute-run surfaces"
    }

    $decision = [string]$normalExecute.composite_quality.cloud_policy_decision
    if ($decision -notin @("pass", "warn")) {
        throw "Flow A expected cloud_policy_decision to be pass or warn, got $decision"
    }

    $normalExport = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase7-normal-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if (-not $normalExport.run_metadata.PSObject.Properties["composite_quality"]) {
        throw "Flow A export-create missing run_metadata.composite_quality"
    }
    $exportCompositeJson = $normalExport.run_metadata.composite_quality | ConvertTo-Json -Depth 10 -Compress
    if ($exportCompositeJson -ne $runCompositeJson) {
        throw "Flow A export-create run_metadata.composite_quality did not match execute-run run_metadata.composite_quality"
    }

    # Flow B: deterministic cloud policy fail
    Set-Location $failFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $strictPreprocessingConfigPath = Join-Path $failFlowRoot "strict-preprocessing.json"
    $strictPreprocessingConfig = @'
{
  "season_windows": {
    "leaf_on": {
      "start_month": 4,
      "end_month": 9
    },
    "leaf_off": {
      "start_month": 10,
      "end_month": 3
    },
    "dry": {
      "start_month": 6,
      "end_month": 9
    },
    "wet": {
      "start_month": 10,
      "end_month": 5
    }
  },
  "cloud_mask": {
    "provider": "stubbed-cloud-mask",
    "apply_shadow_mask": true,
    "apply_snow_mask": true,
    "max_cloud_probability": 0.2
  },
  "cloud_policy": {
    "clear_scene_cloud_cover_max": 0.0,
    "warning_mean_cloud_cover_max": 0.0,
    "fail_mean_cloud_cover_max": 0.0
  }
}
'@
    [System.IO.File]::WriteAllText(
        $strictPreprocessingConfigPath,
        $strictPreprocessingConfig,
        [System.Text.UTF8Encoding]::new($false)
    )

    $env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH = $strictPreprocessingConfigPath
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $failFlowRoot "phase7-cloud-fail.sqlite3"

    $failInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($failInit.ExitCode -ne 0) {
        throw "Flow B init-db failed.`n$($failInit.StdErr)"
    }

    $failCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase7-cloud-fail-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($failCreate.legal_gate.decision -ne "pass") {
        throw "Flow B create-run expected legal_gate.decision=pass, got $($failCreate.legal_gate.decision)"
    }

    $failExecute = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "execute-run",
        "--run-id", "phase7-cloud-fail-001"
    )
    if ($failExecute.ExitCode -eq 0) {
        throw "Flow B execute-run unexpectedly succeeded under strict cloud policy"
    }
    if (-not $failExecute.StdErr) {
        throw "Flow B expected operator-readable stderr but stderr was empty"
    }
    if ($failExecute.StdErr -notlike "*run blocked by cloud policy*") {
        throw "Flow B expected stderr to include 'run blocked by cloud policy', got: $($failExecute.StdErr)"
    }
    if ($failExecute.StdErr -match "Traceback") {
        throw "Flow B stderr unexpectedly contained a traceback.`n$($failExecute.StdErr)"
    }

    # Outside-cwd safety checks
    if (Test-Path (Join-Path $normalFlowRoot "config")) {
        throw "Flow A copied config into outside working directory"
    }
    if (Test-Path (Join-Path $failFlowRoot "config")) {
        throw "Flow B copied config into outside working directory"
    }
    if (Test-Path (Join-Path $normalFlowRoot "sitecustomize.py")) {
        throw "Flow A created sitecustomize.py in outside working directory"
    }
    if (Test-Path (Join-Path $failFlowRoot "sitecustomize.py")) {
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

Write-Host "Phase 7 composite release verification passed."
