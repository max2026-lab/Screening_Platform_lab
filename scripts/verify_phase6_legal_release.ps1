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

function Assert-ReadableFailure {
    param(
        [Parameter(Mandatory = $true)]
        [pscustomobject] $Result,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedMessage
    )

    if ($Result.ExitCode -eq 0) {
        throw "Expected command failure but exit code was 0"
    }
    if (-not $Result.StdErr) {
        throw "Expected operator-readable stderr but stderr was empty"
    }
    if ($Result.StdErr -notlike "*$ExpectedMessage*") {
        throw "Expected stderr to include '$ExpectedMessage', got: $($Result.StdErr)"
    }
    if ($Result.StdErr -match "Traceback") {
        throw "stderr unexpectedly contained a traceback.`n$($Result.StdErr)"
    }
}

function Get-RunLegalGate {
    param(
        [Parameter(Mandatory = $true)]
        [string] $DbPath,

        [Parameter(Mandatory = $true)]
        [string] $RunId
    )

    $pythonCode = @'
import json
import sqlite3
import sys

db_path = sys.argv[1]
run_id = sys.argv[2]

with sqlite3.connect(db_path) as conn:
    row = conn.execute(
        """
        SELECT
            legal_attestation_status,
            legal_geofence_status,
            legal_gate_decision,
            legal_gate_reason,
            legal_gate_evaluated_at
        FROM runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()

if row is None:
    print("null")
else:
    print(json.dumps({
        "attestation_status": row[0],
        "geofence_status": row[1],
        "decision": row[2],
        "reason": row[3],
        "evaluated_at": row[4],
    }))
'@

    $result = Invoke-ProcessCapture -FilePath "python" -Arguments @("-c", $pythonCode, $DbPath, $RunId)
    if ($result.ExitCode -ne 0) {
        $details = if ($result.StdErr) { $result.StdErr } else { $result.StdOut }
        throw "python sqlite query failed.`n$details"
    }
    if (-not $result.StdOut -or $result.StdOut -eq "null") {
        return $null
    }
    return ($result.StdOut | ConvertFrom-Json)
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase6-legal-release-verify-" + [guid]::NewGuid().ToString())
$allowedFlowRoot = Join-Path $baseTempRoot "allowed"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $allowedFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$blockedAoiPath = Join-Path $repoRoot "tests\fixtures\blocked_aoi.geojson"

$originalLocation = Get-Location
try {
    # Allowed path smoke
    Set-Location $allowedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $allowedFlowRoot "phase6-allowed.sqlite3"

    $allowedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($allowedInit.ExitCode -ne 0) {
        throw "Allowed flow init-db failed.`n$($allowedInit.StdErr)"
    }

    $allowedCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase6-allowed-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($allowedCreate.legal_gate.decision -ne "pass") {
        throw "Allowed create-run expected legal_gate.decision=pass, got $($allowedCreate.legal_gate.decision)"
    }

    $allowedExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase6-allowed-001")
    if ($allowedExecute.run_metadata.legal_gate.decision -ne "pass") {
        throw "Allowed execute-run expected run_metadata.legal_gate.decision=pass, got $($allowedExecute.run_metadata.legal_gate.decision)"
    }

    # Missing attestation denial
    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase6-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }

    $missingAttestationCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--geofence", "clear",
        "--run-id", "phase6-missing-attestation-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    Assert-ReadableFailure -Result $missingAttestationCreate -ExpectedMessage "attestation status must be present"

    $missingAttestationGate = Get-RunLegalGate -DbPath $env:LAWFUL_ANOMALY_DB_PATH -RunId "phase6-missing-attestation-001"
    if ($null -eq $missingAttestationGate) {
        throw "Expected denied run phase6-missing-attestation-001 to be persisted"
    }
    if ($missingAttestationGate.decision -ne "fail") {
        throw "Expected persisted denied run to have legal gate decision=fail, got $($missingAttestationGate.decision)"
    }

    # Blocked geofence denial
    $blockedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase6-blocked-geofence-001",
        "--aoi-path", $blockedAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    Assert-ReadableFailure -Result $blockedCreate -ExpectedMessage "deterministic geofence policy blocked AOI"

    $blockedExecute = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "execute-run",
        "--run-id", "phase6-blocked-geofence-001"
    )
    Assert-ReadableFailure -Result $blockedExecute -ExpectedMessage "blocked by legal gate"

    # Outside-cwd safety checks
    if (Test-Path (Join-Path $allowedFlowRoot "config")) {
        throw "Allowed flow copied config into outside working directory"
    }
    if (Test-Path (Join-Path $deniedFlowRoot "config")) {
        throw "Denied flow copied config into outside working directory"
    }
    if (Test-Path (Join-Path $allowedFlowRoot "sitecustomize.py")) {
        throw "Allowed flow created sitecustomize.py in outside working directory"
    }
    if (Test-Path (Join-Path $deniedFlowRoot "sitecustomize.py")) {
        throw "Denied flow created sitecustomize.py in outside working directory"
    }

    Set-Location $repoRoot
    $repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
    if ($repoStatus) {
        throw "Repository is not clean after verification.`n$repoStatus"
    }
}
finally {
    Set-Location $originalLocation
}

Write-Host "Phase 6 legal release verification passed."
