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

function Invoke-LawfulJsonAllowFail {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    return Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments $Arguments
}

function Assert-JsonFieldsPresent {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Object,

        [Parameter(Mandatory = $true)]
        [string[]] $Fields,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    foreach ($field in $Fields) {
        if (-not $Object.PSObject.Properties[$field]) {
            throw "$Context missing field '$field'"
        }
    }
}

function Assert-NoTraceback {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string] $Text,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if ($Text -match "Traceback") {
        throw "$Context stderr unexpectedly contained a traceback.`n$Text"
    }
}

function Assert-TextIncludes {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Text,

        [Parameter(Mandatory = $true)]
        [string] $Expected,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if (-not $Text.Contains($Expected)) {
        throw "$Context expected text to include '$Expected'"
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase22-calibration-registry-snapshot-diff-release-" + [guid]::NewGuid().ToString())
$readyFlowRoot = Join-Path $baseTempRoot "ready"
$incompleteFlowRoot = Join-Path $baseTempRoot "incomplete"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
$registryFlowRoot = Join-Path $baseTempRoot "registry"
$emptyRegistryRoot = Join-Path $baseTempRoot "empty-registry"
$invalidFlowRoot = Join-Path $baseTempRoot "invalid"

New-Item -ItemType Directory -Path $readyFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $incompleteFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $registryFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $emptyRegistryRoot -Force | Out-Null
New-Item -ItemType Directory -Path $invalidFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location

try {
    # ============================================================
    # READY ARTIFACT GENERATION
    # ============================================================
    Set-Location $readyFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase22-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase22-snapshot-diff-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase22-snapshot-diff-ready-001")
    $candidateCount = [int]$executeRun.candidate_count

    $topReviewWindow = [Math]::Min($candidateCount, 20)
    $requiredReviewCount = [Math]::Max(
        [int][Math]::Ceiling($candidateCount * 0.20),
        [int][Math]::Ceiling($topReviewWindow * 0.50)
    )
    if ($requiredReviewCount -lt 2) {
        $requiredReviewCount = 2
    }

    $reviewQueue = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase22-snapshot-diff-ready-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidates = @($reviewQueue)

    $approveCount = [Math]::Max(1, [int][Math]::Floor($requiredReviewCount / 2))
    $watchCount = $requiredReviewCount - $approveCount
    if ($watchCount -lt 1) {
        $watchCount = 1
        $approveCount = $requiredReviewCount - 1
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -First $approveCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase22-snapshot-diff-ready-001",
            "--reviewer-id", "phase22-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase22 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase22-snapshot-diff-ready-001",
            "--reviewer-id", "phase22-verifier",
            "--decision", "watch",
            "--note", "phase22 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase22-snapshot-diff-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase22-snapshot-diff-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase22-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase22-snapshot-diff-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase22-snapshot-diff-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase22-snapshot-diff-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase22-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase22-snapshot-diff-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    Assert-NoTraceback -Text $deniedCreateResult.StdErr -Context "Denied create-run"
    if ($deniedCreateResult.ExitCode -eq 0) {
        throw "Legal-denied create-run expected non-zero exit code"
    }

    $deniedArtifactDir = Join-Path $deniedFlowRoot "artifact-denied"
    $deniedExportResult = Invoke-LawfulJsonAllowFail -Arguments @(
        "calibration-label-export",
        "--run-id", "phase22-snapshot-diff-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Denied export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # FRESH REGISTRY DB PROOF
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase22-registry.sqlite3"

    $regInitResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($regInitResult.ExitCode -ne 0) {
        throw "Registry init-db failed.`n$($regInitResult.StdErr)"
    }

    $readyRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    )
    Assert-NoTraceback -Text $readyRegisterResult.StdErr -Context "Ready register"
    if ($readyRegisterResult.ExitCode -ne 0) {
        throw "Ready register failed.`n$($readyRegisterResult.StdErr)"
    }
    $readyRegister = $readyRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$readyRegister.status -ne "registered") { throw "Ready register expected status=registered" }
    if ([string]$readyRegister.artifact_status -ne "ready") { throw "Ready register expected artifact_status=ready" }

    $incompleteRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $incompleteArtifactDir
    )
    Assert-NoTraceback -Text $incompleteRegisterResult.StdErr -Context "Incomplete register"
    if ($incompleteRegisterResult.ExitCode -ne 0) {
        throw "Incomplete register failed.`n$($incompleteRegisterResult.StdErr)"
    }
    $incompleteRegister = $incompleteRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$incompleteRegister.status -ne "registered") { throw "Incomplete register expected status=registered" }
    if ([string]$incompleteRegister.artifact_status -ne "incomplete") { throw "Incomplete register expected artifact_status=incomplete" }

    $deniedRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedRegisterResult.StdErr -Context "Denied register"
    if ($deniedRegisterResult.ExitCode -ne 0) {
        throw "Denied register failed.`n$($deniedRegisterResult.StdErr)"
    }
    $deniedRegister = $deniedRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$deniedRegister.status -ne "registered") { throw "Denied register expected status=registered" }
    if ([string]$deniedRegister.artifact_status -ne "fail") { throw "Denied register expected artifact_status=fail" }

    # ============================================================
    # EMPTY REGISTRY SNAPSHOT EXPORT
    # ============================================================
    Set-Location $emptyRegistryRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase22-empty-registry.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null

    $emptySnapshotDir = Join-Path $emptyRegistryRoot "snapshot-empty"
    $emptyExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $emptySnapshotDir
    )
    Assert-NoTraceback -Text $emptyExportResult.StdErr -Context "Empty registry snapshot export"
    if ($emptyExportResult.ExitCode -ne 0) {
        throw "Empty registry snapshot export failed.`n$($emptyExportResult.StdErr)"
    }

    # ============================================================
    # FULL REGISTRY SNAPSHOT EXPORTS
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase22-registry.sqlite3"

    $fullSnapshotDir = Join-Path $registryFlowRoot "snapshot-full"
    $fullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $fullSnapshotDir
    )
    Assert-NoTraceback -Text $fullExportResult.StdErr -Context "Full registry snapshot export"
    if ($fullExportResult.ExitCode -ne 0) {
        throw "Full registry snapshot export failed.`n$($fullExportResult.StdErr)"
    }

    $fullExport = $fullExportResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $fullExport -Fields @(
        "status", "reasons", "output_dir", "artifact_count", "snapshot_hash", "files", "file_hashes"
    ) -Context "Full registry snapshot JSON"
    if ([string]$fullExport.status -ne "exported") { throw "Full export expected status=exported" }
    if ([int]$fullExport.artifact_count -ne 3) { throw "Full export expected artifact_count=3" }
    if (-not [string]$fullExport.snapshot_hash) { throw "Full export expected snapshot_hash non-empty" }

    $secondFullSnapshotDir = Join-Path $registryFlowRoot "snapshot-full-second"
    $secondFullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $secondFullSnapshotDir
    )
    Assert-NoTraceback -Text $secondFullExportResult.StdErr -Context "Second full registry snapshot export"
    if ($secondFullExportResult.ExitCode -ne 0) {
        throw "Second full registry snapshot export failed.`n$($secondFullExportResult.StdErr)"
    }

    $secondFullExport = $secondFullExportResult.StdOut | ConvertFrom-Json
    if ([string]$secondFullExport.snapshot_hash -ne [string]$fullExport.snapshot_hash) {
        throw "Second full export expected same snapshot_hash as first full export"
    }

    # ============================================================
    # PLUS-ONE REGISTRY SNAPSHOT EXPORT
    # ============================================================
    # Create a second ready artifact in the ready flow
    Set-Location $readyFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase22-generation.sqlite3"
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase22-snapshot-diff-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase22-snapshot-diff-ready-002") | Out-Null
    $queue002 = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase22-snapshot-diff-ready-002",
        "--limit", "1"
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase22-snapshot-diff-ready-002",
        "--reviewer-id", "phase22-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase22 approve"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase22-snapshot-diff-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null
    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase22-snapshot-diff-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase22-registry.sqlite3"
    $plusOneRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir2
    )
    Assert-NoTraceback -Text $plusOneRegisterResult.StdErr -Context "Plus-one register"
    if ($plusOneRegisterResult.ExitCode -ne 0) {
        throw "Plus-one register failed.`n$($plusOneRegisterResult.StdErr)"
    }

    $plusOneSnapshotDir = Join-Path $registryFlowRoot "snapshot-plus-one"
    $plusOneExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $plusOneSnapshotDir
    )
    Assert-NoTraceback -Text $plusOneExportResult.StdErr -Context "Plus-one registry snapshot export"
    if ($plusOneExportResult.ExitCode -ne 0) {
        throw "Plus-one registry snapshot export failed.`n$($plusOneExportResult.StdErr)"
    }

    $plusOneExport = $plusOneExportResult.StdOut | ConvertFrom-Json
    if ([int]$plusOneExport.artifact_count -ne 4) { throw "Plus-one export expected artifact_count=4" }
    if ([string]$plusOneExport.snapshot_hash -eq [string]$fullExport.snapshot_hash) {
        throw "Plus-one export expected different snapshot_hash than full export"
    }

    # ============================================================
    # OFFLINE PROOF: REMOVE DB PATH BEFORE ALL DIFF COMMANDS
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # HELPER FUNCTIONS
    # ============================================================
    function Assert-ValidDiffResult {
        param(
            [Parameter(Mandatory = $true)]
            [object] $Result,

            [Parameter(Mandatory = $true)]
            [string] $Context
        )
        Assert-NoTraceback -Text $Result.StdErr -Context $Context
        if ($Result.ExitCode -ne 0) { throw "$Context expected exit 0.`n$($Result.StdOut)`n$($Result.StdErr)" }
        if (-not $Result.StdOut) { throw "$Context returned empty output" }
        $parsed = $Result.StdOut | ConvertFrom-Json
        if ([string]$parsed.status -ne "compared") { throw "$Context expected status=compared" }
        $requiredFields = @(
            "status", "reasons", "before_snapshot_dir", "after_snapshot_dir",
            "before_snapshot_hash", "after_snapshot_hash", "before_artifact_count",
            "after_artifact_count", "added_count", "removed_count", "changed_count",
            "unchanged_count", "diff_hash", "added", "removed", "changed", "unchanged",
            "before_valid", "after_valid"
        )
        Assert-JsonFieldsPresent -Object $parsed -Fields $requiredFields -Context "$Context JSON"
        return $parsed
    }

    function Assert-InvalidDiffResult {
        param(
            [Parameter(Mandatory = $true)]
            [object] $Result,

            [Parameter(Mandatory = $true)]
            [string] $Context
        )
        Assert-NoTraceback -Text $Result.StdErr -Context $Context
        if ($Result.ExitCode -eq 0) { throw "$Context expected non-zero exit code" }
        if (-not $Result.StdOut) { throw "$Context returned empty output" }
        $parsed = $Result.StdOut | ConvertFrom-Json
        if ([string]$parsed.status -ne "invalid") { throw "$Context expected status=invalid" }
        if ($parsed.reasons.Count -eq 0) { throw "$Context expected non-empty reasons" }
        return $parsed
    }

    function Copy-Snapshot {
        param(
            [Parameter(Mandatory = $true)]
            [string] $Name,

            [Parameter(Mandatory = $false)]
            [string] $SourceDir = $fullSnapshotDir
        )
        $dest = Join-Path $invalidFlowRoot $Name
        Copy-Item -Path $SourceDir -Destination $dest -Recurse -Force
        return $dest
    }

    # ============================================================
    # EMPTY VS EMPTY DIFF
    # ============================================================
    $emptyDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir
    )
    $emptyDiff = Assert-ValidDiffResult -Result $emptyDiffResult -Context "Empty vs empty diff"
    if ([int]$emptyDiff.before_artifact_count -ne 0) { throw "Empty diff expected before_artifact_count=0" }
    if ([int]$emptyDiff.after_artifact_count -ne 0) { throw "Empty diff expected after_artifact_count=0" }
    if ([int]$emptyDiff.added_count -ne 0) { throw "Empty diff expected added_count=0" }
    if ([int]$emptyDiff.removed_count -ne 0) { throw "Empty diff expected removed_count=0" }
    if ([int]$emptyDiff.changed_count -ne 0) { throw "Empty diff expected changed_count=0" }
    if ([int]$emptyDiff.unchanged_count -ne 0) { throw "Empty diff expected unchanged_count=0" }
    if (-not [string]$emptyDiff.diff_hash) { throw "Empty diff expected diff_hash non-empty" }
    if ($emptyDiff.before_valid -ne $true) { throw "Empty diff expected before_valid=true" }
    if ($emptyDiff.after_valid -ne $true) { throw "Empty diff expected after_valid=true" }

    # ============================================================
    # FULL VS FULL DIFF
    # ============================================================
    $fullDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $secondFullSnapshotDir
    )
    $fullDiff = Assert-ValidDiffResult -Result $fullDiffResult -Context "Full vs full diff"
    if ([int]$fullDiff.before_artifact_count -ne 3) { throw "Full diff expected before_artifact_count=3" }
    if ([int]$fullDiff.after_artifact_count -ne 3) { throw "Full diff expected after_artifact_count=3" }
    if ([int]$fullDiff.added_count -ne 0) { throw "Full diff expected added_count=0" }
    if ([int]$fullDiff.removed_count -ne 0) { throw "Full diff expected removed_count=0" }
    if ([int]$fullDiff.changed_count -ne 0) { throw "Full diff expected changed_count=0" }
    if ([int]$fullDiff.unchanged_count -ne 3) { throw "Full diff expected unchanged_count=3" }
    if ($fullDiff.before_valid -ne $true) { throw "Full diff expected before_valid=true" }
    if ($fullDiff.after_valid -ne $true) { throw "Full diff expected after_valid=true" }
    if (-not [string]$fullDiff.diff_hash) { throw "Full diff expected diff_hash non-empty" }

    $unchangedRunIds = @($fullDiff.unchanged | ForEach-Object { [string]$_.run_id })
    $expectedRunIds = @("phase22-snapshot-diff-denied-001", "phase22-snapshot-diff-incomplete-001", "phase22-snapshot-diff-ready-001")
    if (($unchangedRunIds | ConvertTo-Json -Compress) -ne ($expectedRunIds | ConvertTo-Json -Compress)) {
        throw "Full diff unchanged run_ids mismatch"
    }

    # ============================================================
    # EMPTY VS FULL DIFF
    # ============================================================
    $emptyFullResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $fullSnapshotDir
    )
    $emptyFull = Assert-ValidDiffResult -Result $emptyFullResult -Context "Empty vs full diff"
    if ([int]$emptyFull.added_count -ne 3) { throw "Empty vs full expected added_count=3" }
    if ([int]$emptyFull.removed_count -ne 0) { throw "Empty vs full expected removed_count=0" }
    if ([int]$emptyFull.changed_count -ne 0) { throw "Empty vs full expected changed_count=0" }
    if ([int]$emptyFull.unchanged_count -ne 0) { throw "Empty vs full expected unchanged_count=0" }

    $addedStatuses = @($emptyFull.added | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $addedStatuses -or "incomplete" -notin $addedStatuses -or "fail" -notin $addedStatuses) {
        throw "Empty vs full expected added statuses to include ready, incomplete, fail"
    }
    foreach ($artifact in $emptyFull.added) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @("artifact_hash", "run_id", "artifact_status", "label_count", "include_pending") -Context "Empty vs full added row"
    }

    # ============================================================
    # FULL VS EMPTY DIFF
    # ============================================================
    $fullEmptyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir
    )
    $fullEmpty = Assert-ValidDiffResult -Result $fullEmptyResult -Context "Full vs empty diff"
    if ([int]$fullEmpty.added_count -ne 0) { throw "Full vs empty expected added_count=0" }
    if ([int]$fullEmpty.removed_count -ne 3) { throw "Full vs empty expected removed_count=3" }
    if ([int]$fullEmpty.changed_count -ne 0) { throw "Full vs empty expected changed_count=0" }
    if ([int]$fullEmpty.unchanged_count -ne 0) { throw "Full vs empty expected unchanged_count=0" }

    $removedStatuses = @($fullEmpty.removed | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $removedStatuses -or "incomplete" -notin $removedStatuses -or "fail" -notin $removedStatuses) {
        throw "Full vs empty expected removed statuses to include ready, incomplete, fail"
    }
    foreach ($artifact in $fullEmpty.removed) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @("artifact_hash", "run_id", "artifact_status", "label_count", "include_pending") -Context "Full vs empty removed row"
    }

    # ============================================================
    # PLUS-ONE DIFF
    # ============================================================
    $plusOneDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    $plusOneDiff = Assert-ValidDiffResult -Result $plusOneDiffResult -Context "Plus-one diff"
    if ([int]$plusOneDiff.added_count -ne 1) { throw "Plus-one diff expected added_count=1" }
    if ([int]$plusOneDiff.removed_count -ne 0) { throw "Plus-one diff expected removed_count=0" }
    if ([int]$plusOneDiff.changed_count -ne 0) { throw "Plus-one diff expected changed_count=0" }
    if ([int]$plusOneDiff.unchanged_count -ne 3) { throw "Plus-one diff expected unchanged_count=3" }
    if ([string]$plusOneDiff.added[0].run_id -ne "phase22-snapshot-diff-ready-002") { throw "Plus-one diff expected added run_id=phase22-snapshot-diff-ready-002" }
    if ([string]$plusOneDiff.diff_hash -eq [string]$fullDiff.diff_hash) { throw "Plus-one diff expected diff_hash different from full-vs-full diff_hash" }

    # ============================================================
    # DETERMINISM
    # ============================================================
    $plusOneDiffResult2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    $plusOneDiff2 = Assert-ValidDiffResult -Result $plusOneDiffResult2 -Context "Plus-one diff repeat"
    if ([string]$plusOneDiff2.diff_hash -ne [string]$plusOneDiff.diff_hash) {
        throw "Plus-one diff expected same diff_hash on repeated run"
    }

    $copiedFull = Join-Path $invalidFlowRoot "copied-full"
    $copiedPlusOne = Join-Path $invalidFlowRoot "copied-plus-one"
    Copy-Item -Path $fullSnapshotDir -Destination $copiedFull -Recurse -Force
    Copy-Item -Path $plusOneSnapshotDir -Destination $copiedPlusOne -Recurse -Force

    $copiedDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $copiedFull,
        "--after-snapshot-dir", $copiedPlusOne
    )
    $copiedDiff = Assert-ValidDiffResult -Result $copiedDiffResult -Context "Copied plus-one diff"
    if ([string]$copiedDiff.diff_hash -ne [string]$plusOneDiff.diff_hash) {
        throw "Copied plus-one diff expected same diff_hash as original"
    }
    if ([string]$copiedDiff.before_snapshot_dir -eq [string]$plusOneDiff.before_snapshot_dir) {
        throw "Copied plus-one diff expected different before_snapshot_dir"
    }
    if ([string]$copiedDiff.after_snapshot_dir -eq [string]$plusOneDiff.after_snapshot_dir) {
        throw "Copied plus-one diff expected different after_snapshot_dir"
    }

    # ============================================================
    # CHANGED-ARTIFACT SMOKE
    # ============================================================
    # Create a second registry DB with same artifacts but one changed label_count
    $changedRegistryRoot = Join-Path $baseTempRoot "changed-registry"
    New-Item -ItemType Directory -Path $changedRegistryRoot -Force | Out-Null
    Set-Location $changedRegistryRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $changedRegistryRoot "phase22-changed-registry.sqlite3"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null

    $readyRegisterResult2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    )
    Assert-NoTraceback -Text $readyRegisterResult2.StdErr -Context "Changed registry ready register"
    if ($readyRegisterResult2.ExitCode -ne 0) { throw "Changed registry ready register failed" }

    $incompleteRegisterResult2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $incompleteArtifactDir
    )
    Assert-NoTraceback -Text $incompleteRegisterResult2.StdErr -Context "Changed registry incomplete register"
    if ($incompleteRegisterResult2.ExitCode -ne 0) { throw "Changed registry incomplete register failed" }

    $deniedRegisterResult2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedRegisterResult2.StdErr -Context "Changed registry denied register"
    if ($deniedRegisterResult2.ExitCode -ne 0) { throw "Changed registry denied register failed" }

    # Update label_count for ready artifact directly in DB
    $updateReadyLabelCount = @"
import sqlite3, json, sys
path = sys.argv[1]
conn = sqlite3.connect(path)
cur = conn.cursor()
cur.execute("SELECT artifact_hash, artifact_status, label_count FROM calibration_label_artifacts WHERE run_id = ?", ("phase22-snapshot-diff-ready-001",))
row = cur.fetchone()
if row is None:
    sys.exit("Ready artifact not found")
new_count = row[2] + 1
cur.execute("UPDATE calibration_label_artifacts SET label_count = ? WHERE run_id = ?", (new_count, "phase22-snapshot-diff-ready-001"))
conn.commit()
conn.close()
"@
    $updateScriptPath = Join-Path $changedRegistryRoot "update_label_count.py"
    Set-Content -Path $updateScriptPath -Value $updateReadyLabelCount -Encoding UTF8
    python $updateScriptPath $env:LAWFUL_ANOMALY_DB_PATH
    if ($LASTEXITCODE -ne 0) { throw "Python label_count update failed" }

    $changedSnapshotDir = Join-Path $changedRegistryRoot "snapshot-changed"
    $changedExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $changedSnapshotDir
    )
    Assert-NoTraceback -Text $changedExportResult.StdErr -Context "Changed registry snapshot export"
    if ($changedExportResult.ExitCode -ne 0) {
        throw "Changed registry snapshot export failed.`n$($changedExportResult.StdErr)"
    }

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $changedDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $changedSnapshotDir
    )
    $changedDiff = Assert-ValidDiffResult -Result $changedDiffResult -Context "Changed artifact diff"
    if ([int]$changedDiff.changed_count -ne 1) { throw "Changed diff expected changed_count=1" }
    if ([int]$changedDiff.added_count -ne 0) { throw "Changed diff expected added_count=0" }
    if ([int]$changedDiff.removed_count -ne 0) { throw "Changed diff expected removed_count=0" }
    if ([int]$changedDiff.unchanged_count -ne 2) { throw "Changed diff expected unchanged_count=2" }

    $changedRow = $changedDiff.changed[0]
    Assert-JsonFieldsPresent -Object $changedRow -Fields @("artifact_hash", "before", "after", "changed_fields") -Context "Changed row"
    $beforeExpected = @("run_id", "artifact_status", "label_pack_hash", "label_manifest_hash", "label_count", "include_pending", "files", "file_hashes")
    Assert-JsonFieldsPresent -Object $changedRow.before -Fields $beforeExpected -Context "Changed row before"
    Assert-JsonFieldsPresent -Object $changedRow.after -Fields $beforeExpected -Context "Changed row after"

    $fieldStrings = @($changedRow.changed_fields | ForEach-Object { [string]$_ })
    $sortedFields = @($fieldStrings | Sort-Object)
    if (($fieldStrings | ConvertTo-Json -Compress) -ne ($sortedFields | ConvertTo-Json -Compress)) {
        throw "Changed fields expected to be sorted alphabetically"
    }
    if ("label_count" -notin $fieldStrings) { throw "Changed fields expected to include label_count" }

    # ============================================================
    # MARKDOWN STDOUT SMOKE
    # ============================================================
    $mdDiffResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdDiffResult.StdErr -Context "Markdown diff"
    if ($mdDiffResult.ExitCode -ne 0) { throw "Markdown diff expected exit 0" }
    $mdDiffOut = $mdDiffResult.StdOut
    Assert-TextIncludes -Text $mdDiffOut -Expected "# Calibration Registry Snapshot Diff" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Status:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Diff hash:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Before snapshot hash:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "After snapshot hash:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Added:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Removed:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Changed:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "Unchanged:" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "## Reasons" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "## Added Artifacts" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "## Removed Artifacts" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "## Changed Artifacts" -Context "Markdown diff"
    Assert-TextIncludes -Text $mdDiffOut -Expected "## Unchanged Artifacts" -Context "Markdown diff"

    # ============================================================
    # INVALID SNAPSHOT SMOKES
    # ============================================================
    # Tamper before JSON
    $tamperBeforeDir = Copy-Snapshot -Name "tamper-before" -SourceDir $fullSnapshotDir
    $tbJsonPath = Join-Path $tamperBeforeDir "calibration_artifact_registry.json"
    $tb = Get-Content $tbJsonPath -Raw | ConvertFrom-Json
    $tb.artifact_count = 999
    $tb | ConvertTo-Json -Depth 10 | Set-Content $tbJsonPath -NoNewline
    Add-Content -Path $tbJsonPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $tamperBeforeDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Tamper before JSON"
    if ($parsed.before_valid -ne $false) { throw "Tamper before expected before_valid=false" }
    if ($parsed.after_valid -ne $true) { throw "Tamper before expected after_valid=true" }

    # Tamper after JSON
    $tamperAfterDir = Copy-Snapshot -Name "tamper-after" -SourceDir $plusOneSnapshotDir
    $taJsonPath = Join-Path $tamperAfterDir "calibration_artifact_registry.json"
    $ta = Get-Content $taJsonPath -Raw | ConvertFrom-Json
    $ta.artifact_count = 999
    $ta | ConvertTo-Json -Depth 10 | Set-Content $taJsonPath -NoNewline
    Add-Content -Path $taJsonPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $tamperAfterDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Tamper after JSON"
    if ($parsed.before_valid -ne $true) { throw "Tamper after expected before_valid=true" }
    if ($parsed.after_valid -ne $false) { throw "Tamper after expected after_valid=false" }

    # Delete before MD
    $deleteBeforeMdDir = Copy-Snapshot -Name "delete-before-md" -SourceDir $fullSnapshotDir
    Remove-Item (Join-Path $deleteBeforeMdDir "calibration_artifact_registry.md") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $deleteBeforeMdDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Delete before MD"
    if ($parsed.before_valid -ne $false) { throw "Delete before MD expected before_valid=false" }

    # Delete after SHA256SUMS
    $deleteAfterSumsDir = Copy-Snapshot -Name "delete-after-sums" -SourceDir $plusOneSnapshotDir
    Remove-Item (Join-Path $deleteAfterSumsDir "SHA256SUMS.txt") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $deleteAfterSumsDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Delete after SHA256SUMS"
    if ($parsed.after_valid -ne $false) { throw "Delete after SHA256SUMS expected after_valid=false" }

    # Malformed before artifacts = "bad"
    $badArtifactsDir = Copy-Snapshot -Name "bad-artifacts" -SourceDir $fullSnapshotDir
    $baPath = Join-Path $badArtifactsDir "calibration_artifact_registry.json"
    $ba = Get-Content $baPath -Raw | ConvertFrom-Json
    $ba.artifacts = "bad"
    $ba | ConvertTo-Json -Depth 10 | Set-Content $baPath -NoNewline
    Add-Content -Path $baPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $badArtifactsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    Assert-InvalidDiffResult -Result $r -Context "Malformed artifacts string" | Out-Null

    # Inject coordinate field into after first artifact
    $coordDir = Copy-Snapshot -Name "coord-injected" -SourceDir $plusOneSnapshotDir
    $cPath = Join-Path $coordDir "calibration_artifact_registry.json"
    $c = Get-Content $cPath -Raw | ConvertFrom-Json
    $c.artifacts[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    $c | ConvertTo-Json -Depth 10 | Set-Content $cPath -NoNewline
    Add-Content -Path $cPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $coordDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Coordinate field injected"
    if ($parsed.after_valid -ne $false) { throw "Coordinate injected expected after_valid=false" }

    # Inject label payload field into before first artifact
    $labelsDir = Copy-Snapshot -Name "labels-injected" -SourceDir $fullSnapshotDir
    $lPath = Join-Path $labelsDir "calibration_artifact_registry.json"
    $l = Get-Content $lPath -Raw | ConvertFrom-Json
    $l.artifacts[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    $l | ConvertTo-Json -Depth 10 | Set-Content $lPath -NoNewline
    Add-Content -Path $lPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $labelsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir
    )
    $parsed = Assert-InvalidDiffResult -Result $r -Context "Label payload field injected"
    if ($parsed.before_valid -ne $false) { throw "Labels injected expected before_valid=false" }

    # ============================================================
    # INVALID MARKDOWN SMOKE
    # ============================================================
    $invalidMdResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff",
        "--before-snapshot-dir", $badArtifactsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $invalidMdResult.StdErr -Context "Invalid markdown diff"
    if ($invalidMdResult.ExitCode -eq 0) { throw "Invalid markdown diff expected non-zero exit code" }
    $invalidMdOut = $invalidMdResult.StdOut
    Assert-TextIncludes -Text $invalidMdOut -Expected "# Calibration Registry Snapshot Diff" -Context "Invalid markdown diff"
    Assert-TextIncludes -Text $invalidMdOut -Expected "Status:" -Context "Invalid markdown diff"
    Assert-TextIncludes -Text $invalidMdOut -Expected "## Reasons" -Context "Invalid markdown diff"

    # ============================================================
    # SAFETY: NO FULL LABEL PAYLOAD OR COORDINATE FIELDS
    # ============================================================
    $diffStr = $plusOneDiffResult.StdOut
    if ($diffStr.Contains('"labels"')) { throw "Diff output must not contain full label payload field: labels" }
    if ($diffStr.Contains('"label_ids"')) { throw "Diff output must not contain full label payload field: label_ids" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($diffStr.Contains('"' + $coord + '"')) { throw "Diff output must not contain coordinate field: $coord" }
    }

    $mdDiffStr = $mdDiffOut
    if ($mdDiffStr.Contains("labels")) { throw "Markdown diff must not contain full label payload dump" }
    if ($mdDiffStr.Contains("label_ids")) { throw "Markdown diff must not contain full label payload dump" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($mdDiffStr.Contains($coord)) { throw "Markdown diff must not contain coordinate dump: $coord" }
    }

    # ============================================================
    # OUTSIDE-CWD SAFETY CHECKS
    # ============================================================
    foreach ($flowRoot in @($readyFlowRoot, $incompleteFlowRoot, $deniedFlowRoot, $registryFlowRoot, $emptyRegistryRoot, $invalidFlowRoot, $changedRegistryRoot)) {
        if (Test-Path (Join-Path $flowRoot "config")) {
            throw "Verification copied config into outside working directory: $flowRoot"
        }
        if (Test-Path (Join-Path $flowRoot "sitecustomize.py")) {
            throw "Verification created sitecustomize.py in outside working directory: $flowRoot"
        }
    }
    if (Test-Path Env:PYTHONPATH) {
        throw "PYTHONPATH must not be set after verification flows"
    }

    # ============================================================
    # FINAL REPO CLEANLINESS CHECK
    # ============================================================
    Set-Location $repoRoot
    $repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
    if ($repoStatus) {
        throw "Repository is not clean after verification.`n$repoStatus"
    }
}
finally {
    Set-Location $originalLocation
}

Write-Host "Phase 22 calibration registry snapshot diff release verification passed."
