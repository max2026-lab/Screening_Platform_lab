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

function Assert-AuditManifestShape {
    param(
        [Parameter(Mandatory = $true)]
        [object] $AuditManifest,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if ($null -eq $AuditManifest) {
        throw "$Context missing audit_manifest"
    }

    foreach ($field in @(
        "export_record_id",
        "run_id",
        "created_at",
        "audience",
        "precision_tier",
        "exact_coordinates_included",
        "coordinate_resolution_m",
        "artifact_name_resolution_m",
        "processing_baseline_id",
        "score_formula_version",
        "source_endpoint_id",
        "source_scene_manifest_hash",
        "legal_gate",
        "composite_quality",
        "candidate_count",
        "candidate_ids",
        "top_candidate_id",
        "candidate_score_formula_versions",
        "audit_manifest_hash"
    )) {
        if (-not $AuditManifest.PSObject.Properties[$field]) {
            throw "$Context audit_manifest missing field '$field'"
        }
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase10-export-audit-release-verify-" + [guid]::NewGuid().ToString())
$flowRoot = Join-Path $baseTempRoot "phase10-flow"
New-Item -ItemType Directory -Path $flowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    Set-Location $flowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $flowRoot "phase10-export-audit.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Flow A init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase10-export-audit-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($createRun.legal_gate.decision -ne "pass") {
        throw "Flow A create-run expected legal_gate.decision=pass, got $($createRun.legal_gate.decision)"
    }

    $executeRun = Invoke-LawfulJson -Arguments @(
        "execute-run",
        "--run-id", "phase10-export-audit-001"
    )
    $topCandidateId = [string]$executeRun.top_candidate_id
    if (-not $topCandidateId) {
        throw "Flow A execute-run did not return top_candidate_id"
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase10-export-audit-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportCreateRepeat = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase10-export-audit-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )

    Assert-AuditManifestShape -AuditManifest $exportCreate.audit_manifest -Context "Flow A export-create"

    if ([string]$exportCreate.audit_manifest.run_id -ne "phase10-export-audit-001") {
        throw "Flow A expected audit_manifest.run_id=phase10-export-audit-001, got $($exportCreate.audit_manifest.run_id)"
    }
    if ([string]$exportCreate.audit_manifest.precision_tier -ne "restricted") {
        throw "Flow A expected audit_manifest.precision_tier=restricted, got $($exportCreate.audit_manifest.precision_tier)"
    }
    if ($exportCreate.audit_manifest.exact_coordinates_included -ne $false) {
        throw "Flow A expected audit_manifest.exact_coordinates_included=false"
    }
    if ([string]$exportCreate.audit_manifest.legal_gate.decision -ne "pass") {
        throw "Flow A expected audit_manifest.legal_gate.decision=pass, got $($exportCreate.audit_manifest.legal_gate.decision)"
    }

    $auditCompositeJson = $exportCreate.audit_manifest.composite_quality | ConvertTo-Json -Depth 20 -Compress
    $runCompositeJson = $exportCreate.run_metadata.composite_quality | ConvertTo-Json -Depth 20 -Compress
    if ($auditCompositeJson -ne $runCompositeJson) {
        throw "Flow A expected audit_manifest.composite_quality to equal export run_metadata.composite_quality"
    }

    if ([int]$exportCreate.audit_manifest.candidate_count -ne @($exportCreate.candidates).Count) {
        throw "Flow A expected audit_manifest.candidate_count to match candidates count"
    }

    $auditCandidateIds = @($exportCreate.audit_manifest.candidate_ids | ForEach-Object { [string]$_ })
    $sortedCandidateIds = @($auditCandidateIds | Sort-Object)
    $auditCandidateIdsJson = $auditCandidateIds | ConvertTo-Json -Depth 10 -Compress
    $sortedCandidateIdsJson = $sortedCandidateIds | ConvertTo-Json -Depth 10 -Compress
    if ($auditCandidateIdsJson -ne $sortedCandidateIdsJson) {
        throw "Flow A expected audit_manifest.candidate_ids to be sorted deterministically"
    }

    if ([string]$exportCreate.audit_manifest.top_candidate_id -ne $topCandidateId) {
        throw "Flow A expected audit_manifest.top_candidate_id to equal execute-run top_candidate_id"
    }
    if (-not [string]$exportCreate.audit_manifest.audit_manifest_hash) {
        throw "Flow A expected audit_manifest.audit_manifest_hash to be non-empty"
    }

    if ($exportCreate.precision_tier -ne "restricted") {
        throw "Flow A expected export precision_tier=restricted, got $($exportCreate.precision_tier)"
    }
    if ($exportCreate.exact_coordinates_included -ne $false) {
        throw "Flow A expected restricted export to exclude exact coordinates"
    }
    if (-not $exportCreate.candidates) {
        throw "Flow A expected export candidates"
    }
    if ($null -eq $exportCreate.candidates[0].bounds -or $null -eq $exportCreate.candidates[0].centroid -or $null -eq $exportCreate.candidates[0].clipped_geometry) {
        throw "Flow A expected restricted export candidate bounds, centroid, and clipped_geometry to exist"
    }

    $repeatAuditHash = [string]$exportCreateRepeat.audit_manifest.audit_manifest_hash
    if ([string]$exportCreate.audit_manifest.audit_manifest_hash -ne $repeatAuditHash) {
        throw "Flow A expected repeated export-create audit_manifest_hash to be identical"
    }

    $repeatCandidateIds = @($exportCreateRepeat.audit_manifest.candidate_ids | ForEach-Object { [string]$_ })
    $repeatCandidateIdsJson = $repeatCandidateIds | ConvertTo-Json -Depth 10 -Compress
    if ($auditCandidateIdsJson -ne $repeatCandidateIdsJson) {
        throw "Flow A expected repeated export-create candidate_ids to be identical"
    }

    if (Test-Path (Join-Path $flowRoot "config")) {
        throw "Flow A copied config into outside working directory"
    }
    if (Test-Path (Join-Path $flowRoot "sitecustomize.py")) {
        throw "Flow A created sitecustomize.py in outside working directory"
    }
    if (Test-Path Env:PYTHONPATH) {
        throw "PYTHONPATH must not be set after verification flow"
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

Write-Host "Phase 10 export audit release verification passed."
