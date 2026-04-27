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

function Get-SHA256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath
    )
    return (Get-FileHash $FilePath -Algorithm SHA256).Hash.ToLower()
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase23-calibration-registry-snapshot-diff-export-release-" + [guid]::NewGuid().ToString())
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase23-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase23-diff-export-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase23-diff-export-ready-001")
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
        "--run-id", "phase23-diff-export-ready-001",
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
            "--run-id", "phase23-diff-export-ready-001",
            "--reviewer-id", "phase23-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase23 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase23-diff-export-ready-001",
            "--reviewer-id", "phase23-verifier",
            "--decision", "watch",
            "--note", "phase23 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase23-diff-export-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase23-diff-export-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase23-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase23-diff-export-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase23-diff-export-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase23-diff-export-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase23-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase23-diff-export-denied-001",
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
        "--run-id", "phase23-diff-export-denied-001",
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase23-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase23-empty-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase23-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase23-generation.sqlite3"
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase23-diff-export-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase23-diff-export-ready-002") | Out-Null
    $queue002 = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase23-diff-export-ready-002",
        "--limit", "1"
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase23-diff-export-ready-002",
        "--reviewer-id", "phase23-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase23 approve"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase23-diff-export-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null
    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase23-diff-export-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase23-registry.sqlite3"
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
    # OFFLINE PROOF: REMOVE DB PATH BEFORE ALL DIFF-EXPORT COMMANDS
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # HELPER FUNCTIONS
    # ============================================================
    function Assert-ValidDiffExportResult {
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
            "status", "reasons", "output_dir", "before_snapshot_dir", "after_snapshot_dir",
            "before_snapshot_hash", "after_snapshot_hash", "before_artifact_count",
            "after_artifact_count", "added_count", "removed_count", "changed_count",
            "unchanged_count", "diff_hash", "files", "file_hashes"
        )
        Assert-JsonFieldsPresent -Object $parsed -Fields $requiredFields -Context "$Context JSON"
        return $parsed
    }

    function Assert-InvalidDiffExportResult {
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

    function Assert-EvidencePack {
        param(
            [Parameter(Mandatory = $true)]
            [string] $EvidenceDir,

            [Parameter(Mandatory = $true)]
            [string] $Context,

            [Parameter(Mandatory = $false)]
            [object] $StdoutResult
        )
        $jsonPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.json"
        $mdPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.md"
        $sumsPath = Join-Path $EvidenceDir "SHA256SUMS.txt"

        if (-not (Test-Path $jsonPath)) { throw "$Context missing calibration_registry_snapshot_diff.json" }
        if (-not (Test-Path $mdPath)) { throw "$Context missing calibration_registry_snapshot_diff.md" }
        if (-not (Test-Path $sumsPath)) { throw "$Context missing SHA256SUMS.txt" }

        $evidenceJson = Get-Content $jsonPath -Raw | ConvertFrom-Json
        Assert-JsonFieldsPresent -Object $evidenceJson -Fields @(
            "snapshot_diff_type", "snapshot_diff_version", "status", "reasons",
            "before_snapshot_hash", "after_snapshot_hash", "before_artifact_count",
            "after_artifact_count", "added_count", "removed_count", "changed_count",
            "unchanged_count", "diff_hash", "added", "removed", "changed", "unchanged",
            "before_valid", "after_valid", "files", "file_hashes"
        ) -Context "$Context evidence JSON"

        if ([string]$evidenceJson.snapshot_diff_type -ne "calibration_registry_snapshot_diff") {
            throw "$Context evidence JSON expected snapshot_diff_type=calibration_registry_snapshot_diff"
        }
        if ([int]$evidenceJson.snapshot_diff_version -ne 1) {
            throw "$Context evidence JSON expected snapshot_diff_version=1"
        }

        $actualJsonHash = Get-SHA256Hex -FilePath $jsonPath
        $actualMdHash = Get-SHA256Hex -FilePath $mdPath
        $actualSumsHash = Get-SHA256Hex -FilePath $sumsPath

        # Evidence JSON must contain file_hashes entries for all three files
        # (Evidence JSON uses canonical hashes internally to avoid circular self-reference)
        foreach ($fileName in @("calibration_registry_snapshot_diff.json", "calibration_registry_snapshot_diff.md", "SHA256SUMS.txt")) {
            if (-not $evidenceJson.file_hashes.PSObject.Properties[$fileName]) {
                throw "$Context evidence JSON file_hashes missing $fileName"
            }
        }

        # Stdout file_hashes must match actual file contents for all three files
        if ($null -ne $StdoutResult) {
            if ([string]$StdoutResult.file_hashes."calibration_registry_snapshot_diff.json" -ne $actualJsonHash) {
                throw "$Context stdout file_hash mismatch for .json"
            }
            if ([string]$StdoutResult.file_hashes."calibration_registry_snapshot_diff.md" -ne $actualMdHash) {
                throw "$Context stdout file_hash mismatch for .md"
            }
            if ([string]$StdoutResult.file_hashes."SHA256SUMS.txt" -ne $actualSumsHash) {
                throw "$Context stdout file_hash mismatch for SHA256SUMS.txt"
            }
        }

        # SHA256SUMS.txt must contain actual hashes and no self-hash
        $sumsText = Get-Content $sumsPath -Raw
        if (-not $sumsText.Contains("$actualJsonHash  calibration_registry_snapshot_diff.json")) {
            throw "$Context SHA256SUMS.txt missing correct hash for .json"
        }
        if (-not $sumsText.Contains("$actualMdHash  calibration_registry_snapshot_diff.md")) {
            throw "$Context SHA256SUMS.txt missing correct hash for .md"
        }
        if ($sumsText.Contains("SHA256SUMS.txt")) {
            throw "$Context SHA256SUMS.txt must not contain a self-hash line"
        }

        return $evidenceJson
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
    # EMPTY VS EMPTY DIFF EXPORT
    # ============================================================
    $evidenceEmptyEmpty = Join-Path $invalidFlowRoot "evidence-empty-empty"
    $emptyDiffExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $evidenceEmptyEmpty
    )
    $emptyDiffExport = Assert-ValidDiffExportResult -Result $emptyDiffExportResult -Context "Empty vs empty diff export"
    if ([int]$emptyDiffExport.before_artifact_count -ne 0) { throw "Empty diff export expected before_artifact_count=0" }
    if ([int]$emptyDiffExport.after_artifact_count -ne 0) { throw "Empty diff export expected after_artifact_count=0" }
    if ([int]$emptyDiffExport.added_count -ne 0) { throw "Empty diff export expected added_count=0" }
    if ([int]$emptyDiffExport.removed_count -ne 0) { throw "Empty diff export expected removed_count=0" }
    if ([int]$emptyDiffExport.changed_count -ne 0) { throw "Empty diff export expected changed_count=0" }
    if ([int]$emptyDiffExport.unchanged_count -ne 0) { throw "Empty diff export expected unchanged_count=0" }
    if (-not [string]$emptyDiffExport.diff_hash) { throw "Empty diff export expected diff_hash non-empty" }

    $expectedEvidenceFiles = @(
        "calibration_registry_snapshot_diff.json",
        "calibration_registry_snapshot_diff.md",
        "SHA256SUMS.txt"
    )
    if (($emptyDiffExport.files | ConvertTo-Json -Compress) -ne ($expectedEvidenceFiles | ConvertTo-Json -Compress)) {
        throw "Empty diff export expected files list mismatch"
    }
    foreach ($fileName in $expectedEvidenceFiles) {
        if (-not $emptyDiffExport.file_hashes.PSObject.Properties[$fileName]) {
            throw "Empty diff export stdout file_hashes missing $fileName"
        }
    }

    $emptyEvidenceJson = Assert-EvidencePack -EvidenceDir $evidenceEmptyEmpty -Context "Empty vs empty" -StdoutResult $emptyDiffExport
    if ([int]$emptyEvidenceJson.unchanged_count -ne 0) { throw "Empty evidence JSON expected unchanged_count=0" }

    # ============================================================
    # FULL VS FULL DIFF EXPORT
    # ============================================================
    $evidenceFullFull = Join-Path $invalidFlowRoot "evidence-full-full"
    $fullDiffExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $secondFullSnapshotDir,
        "--output-dir", $evidenceFullFull
    )
    $fullDiffExport = Assert-ValidDiffExportResult -Result $fullDiffExportResult -Context "Full vs full diff export"
    if ([int]$fullDiffExport.before_artifact_count -ne 3) { throw "Full diff export expected before_artifact_count=3" }
    if ([int]$fullDiffExport.after_artifact_count -ne 3) { throw "Full diff export expected after_artifact_count=3" }
    if ([int]$fullDiffExport.added_count -ne 0) { throw "Full diff export expected added_count=0" }
    if ([int]$fullDiffExport.removed_count -ne 0) { throw "Full diff export expected removed_count=0" }
    if ([int]$fullDiffExport.changed_count -ne 0) { throw "Full diff export expected changed_count=0" }
    if ([int]$fullDiffExport.unchanged_count -ne 3) { throw "Full diff export expected unchanged_count=3" }
    if (-not [string]$fullDiffExport.diff_hash) { throw "Full diff export expected diff_hash non-empty" }

    $fullEvidenceJson = Assert-EvidencePack -EvidenceDir $evidenceFullFull -Context "Full vs full" -StdoutResult $fullDiffExport
    if ([int]$fullEvidenceJson.unchanged_count -ne 3) { throw "Full evidence JSON expected unchanged_count=3" }

    # ============================================================
    # EMPTY VS FULL DIFF EXPORT
    # ============================================================
    $evidenceEmptyFull = Join-Path $invalidFlowRoot "evidence-empty-full"
    $emptyFullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $fullSnapshotDir,
        "--output-dir", $evidenceEmptyFull
    )
    $emptyFullExport = Assert-ValidDiffExportResult -Result $emptyFullExportResult -Context "Empty vs full diff export"
    if ([int]$emptyFullExport.added_count -ne 3) { throw "Empty vs full diff export expected added_count=3" }
    if ([int]$emptyFullExport.removed_count -ne 0) { throw "Empty vs full diff export expected removed_count=0" }
    if ([int]$emptyFullExport.changed_count -ne 0) { throw "Empty vs full diff export expected changed_count=0" }
    if ([int]$emptyFullExport.unchanged_count -ne 0) { throw "Empty vs full diff export expected unchanged_count=0" }

    $emptyFullEvidenceJson = Assert-EvidencePack -EvidenceDir $evidenceEmptyFull -Context "Empty vs full" -StdoutResult $emptyFullExport
    $addedStatuses = @($emptyFullEvidenceJson.added | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $addedStatuses -or "incomplete" -notin $addedStatuses -or "fail" -notin $addedStatuses) {
        throw "Empty vs full evidence expected added statuses to include ready, incomplete, fail"
    }
    foreach ($artifact in $emptyFullEvidenceJson.added) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @("artifact_hash", "run_id", "artifact_status", "label_count", "include_pending") -Context "Empty vs full evidence added row"
    }

    # ============================================================
    # FULL VS EMPTY DIFF EXPORT
    # ============================================================
    $evidenceFullEmpty = Join-Path $invalidFlowRoot "evidence-full-empty"
    $fullEmptyExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $evidenceFullEmpty
    )
    $fullEmptyExport = Assert-ValidDiffExportResult -Result $fullEmptyExportResult -Context "Full vs empty diff export"
    if ([int]$fullEmptyExport.added_count -ne 0) { throw "Full vs empty diff export expected added_count=0" }
    if ([int]$fullEmptyExport.removed_count -ne 3) { throw "Full vs empty diff export expected removed_count=3" }
    if ([int]$fullEmptyExport.changed_count -ne 0) { throw "Full vs empty diff export expected changed_count=0" }
    if ([int]$fullEmptyExport.unchanged_count -ne 0) { throw "Full vs empty diff export expected unchanged_count=0" }

    $fullEmptyEvidenceJson = Assert-EvidencePack -EvidenceDir $evidenceFullEmpty -Context "Full vs empty" -StdoutResult $fullEmptyExport
    $removedStatuses = @($fullEmptyEvidenceJson.removed | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $removedStatuses -or "incomplete" -notin $removedStatuses -or "fail" -notin $removedStatuses) {
        throw "Full vs empty evidence expected removed statuses to include ready, incomplete, fail"
    }
    foreach ($artifact in $fullEmptyEvidenceJson.removed) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @("artifact_hash", "run_id", "artifact_status", "label_count", "include_pending") -Context "Full vs empty evidence removed row"
    }

    # ============================================================
    # PLUS-ONE DIFF EXPORT
    # ============================================================
    $evidencePlusOne = Join-Path $invalidFlowRoot "evidence-plus-one"
    $plusOneDiffExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidencePlusOne
    )
    $plusOneDiffExport = Assert-ValidDiffExportResult -Result $plusOneDiffExportResult -Context "Plus-one diff export"
    if ([int]$plusOneDiffExport.added_count -ne 1) { throw "Plus-one diff export expected added_count=1" }
    if ([int]$plusOneDiffExport.removed_count -ne 0) { throw "Plus-one diff export expected removed_count=0" }
    if ([int]$plusOneDiffExport.changed_count -ne 0) { throw "Plus-one diff export expected changed_count=0" }
    if ([int]$plusOneDiffExport.unchanged_count -ne 3) { throw "Plus-one diff export expected unchanged_count=3" }
    if ([string]$plusOneDiffExport.diff_hash -eq [string]$fullDiffExport.diff_hash) {
        throw "Plus-one diff export expected diff_hash different from full-vs-full diff_hash"
    }

    $plusOneEvidenceJson = Assert-EvidencePack -EvidenceDir $evidencePlusOne -Context "Plus-one" -StdoutResult $plusOneDiffExport
    if ([string]$plusOneEvidenceJson.added[0].run_id -ne "phase23-diff-export-ready-002") {
        throw "Plus-one evidence expected added run_id=phase23-diff-export-ready-002"
    }

    # ============================================================
    # DETERMINISM
    # ============================================================
    $evidencePlusOne2 = Join-Path $invalidFlowRoot "evidence-plus-one-2"
    $plusOneDiffExportResult2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidencePlusOne2
    )
    $plusOneDiffExport2 = Assert-ValidDiffExportResult -Result $plusOneDiffExportResult2 -Context "Plus-one diff export repeat"
    if ([string]$plusOneDiffExport2.diff_hash -ne [string]$plusOneDiffExport.diff_hash) {
        throw "Plus-one diff export expected same diff_hash on repeated run"
    }
    Assert-EvidencePack -EvidenceDir $evidencePlusOne2 -Context "Plus-one repeat" -StdoutResult $plusOneDiffExport2 | Out-Null

    $copiedFull = Join-Path $invalidFlowRoot "copied-full"
    $copiedPlusOne = Join-Path $invalidFlowRoot "copied-plus-one"
    Copy-Item -Path $fullSnapshotDir -Destination $copiedFull -Recurse -Force
    Copy-Item -Path $plusOneSnapshotDir -Destination $copiedPlusOne -Recurse -Force

    $evidenceCopied = Join-Path $invalidFlowRoot "evidence-copied"
    $copiedDiffExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $copiedFull,
        "--after-snapshot-dir", $copiedPlusOne,
        "--output-dir", $evidenceCopied
    )
    $copiedDiffExport = Assert-ValidDiffExportResult -Result $copiedDiffExportResult -Context "Copied plus-one diff export"
    if ([string]$copiedDiffExport.diff_hash -ne [string]$plusOneDiffExport.diff_hash) {
        throw "Copied plus-one diff export expected same diff_hash as original"
    }
    if ([string]$copiedDiffExport.before_snapshot_dir -eq [string]$plusOneDiffExport.before_snapshot_dir) {
        throw "Copied plus-one diff export expected different before_snapshot_dir"
    }
    if ([string]$copiedDiffExport.after_snapshot_dir -eq [string]$plusOneDiffExport.after_snapshot_dir) {
        throw "Copied plus-one diff export expected different after_snapshot_dir"
    }
    Assert-EvidencePack -EvidenceDir $evidenceCopied -Context "Copied plus-one" -StdoutResult $copiedDiffExport | Out-Null

    # Evidence files identical across original and copied snapshots
    $originalJson = Get-Content (Join-Path $evidencePlusOne "calibration_registry_snapshot_diff.json") -Raw
    $copiedJson = Get-Content (Join-Path $evidenceCopied "calibration_registry_snapshot_diff.json") -Raw
    if ($originalJson -ne $copiedJson) { throw "Evidence JSON content differs across original and copied snapshots" }

    $originalMd = Get-Content (Join-Path $evidencePlusOne "calibration_registry_snapshot_diff.md") -Raw
    $copiedMd = Get-Content (Join-Path $evidenceCopied "calibration_registry_snapshot_diff.md") -Raw
    if ($originalMd -ne $copiedMd) { throw "Evidence markdown content differs across original and copied snapshots" }

    $originalSums = Get-Content (Join-Path $evidencePlusOne "SHA256SUMS.txt") -Raw
    $copiedSums = Get-Content (Join-Path $evidenceCopied "SHA256SUMS.txt") -Raw
    if ($originalSums -ne $copiedSums) { throw "Evidence SHA256SUMS content differs across original and copied snapshots" }

    # ============================================================
    # MARKDOWN STDOUT SMOKE
    # ============================================================
    $evidenceMdStdout = Join-Path $invalidFlowRoot "evidence-md-stdout"
    $mdDiffExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidenceMdStdout,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdDiffExportResult.StdErr -Context "Markdown diff export"
    if ($mdDiffExportResult.ExitCode -ne 0) { throw "Markdown diff export expected exit 0" }
    $mdDiffExportOut = $mdDiffExportResult.StdOut
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "# Calibration Registry Snapshot Diff Export" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Status:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Output directory:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Diff hash:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Before snapshot hash:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "After snapshot hash:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Added:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Removed:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Changed:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "Unchanged:" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "## Files" -Context "Markdown diff export"
    Assert-TextIncludes -Text $mdDiffExportOut -Expected "## Reasons" -Context "Markdown diff export"
    Assert-EvidencePack -EvidenceDir $evidenceMdStdout -Context "Markdown stdout" | Out-Null

    # ============================================================
    # MARKDOWN EVIDENCE FILE SMOKE
    # ============================================================
    $mdEvidencePath = Join-Path $evidencePlusOne "calibration_registry_snapshot_diff.md"
    $mdEvidenceText = Get-Content $mdEvidencePath -Raw
    Assert-TextIncludes -Text $mdEvidenceText -Expected "# Calibration Registry Snapshot Diff" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Diff hash:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Before snapshot hash:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "After snapshot hash:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Added:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Removed:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Changed:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "Unchanged:" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Files" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Reasons" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Added Artifacts" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Removed Artifacts" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Changed Artifacts" -Context "Markdown evidence file"
    Assert-TextIncludes -Text $mdEvidenceText -Expected "## Unchanged Artifacts" -Context "Markdown evidence file"

    # ============================================================
    # OUTPUT-DIR NON-EMPTY WITHOUT --overwrite
    # ============================================================
    $nonEmptyDir = Join-Path $invalidFlowRoot "nonempty-output"
    New-Item -ItemType Directory -Path $nonEmptyDir -Force | Out-Null
    "keep" | Set-Content (Join-Path $nonEmptyDir "unrelated.txt") -NoNewline
    $nonEmptyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $nonEmptyDir
    )
    Assert-NoTraceback -Text $nonEmptyResult.StdErr -Context "Non-empty output dir"
    if ($nonEmptyResult.ExitCode -eq 0) { throw "Non-empty output dir expected non-zero exit code" }
    $nonEmptyParsed = $nonEmptyResult.StdOut | ConvertFrom-Json
    if ([string]$nonEmptyParsed.status -ne "invalid") { throw "Non-empty output dir expected status=invalid" }
    if (-not (Test-Path (Join-Path $nonEmptyDir "unrelated.txt"))) {
        throw "Non-empty output dir must preserve unrelated files"
    }
    if (Test-Path (Join-Path $nonEmptyDir "calibration_registry_snapshot_diff.json")) {
        throw "Non-empty output dir must not write evidence pack when invalid"
    }

    # ============================================================
    # --overwrite REPLACES KNOWN FILES, PRESERVES UNRELATED
    # ============================================================
    $overwriteDir = Join-Path $invalidFlowRoot "overwrite-output"
    New-Item -ItemType Directory -Path $overwriteDir -Force | Out-Null
    "keep" | Set-Content (Join-Path $overwriteDir "unrelated.txt") -NoNewline
    "old" | Set-Content (Join-Path $overwriteDir "calibration_registry_snapshot_diff.json") -NoNewline

    $overwriteResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $overwriteDir,
        "--overwrite"
    )
    Assert-NoTraceback -Text $overwriteResult.StdErr -Context "Overwrite output dir"
    if ($overwriteResult.ExitCode -ne 0) { throw "Overwrite output dir expected exit 0" }
    $overwriteParsed = $overwriteResult.StdOut | ConvertFrom-Json
    Assert-EvidencePack -EvidenceDir $overwriteDir -Context "Overwrite" -StdoutResult $overwriteParsed | Out-Null
    if (-not (Test-Path (Join-Path $overwriteDir "unrelated.txt"))) {
        throw "Overwrite must preserve unrelated files"
    }
    $replacedJson = Get-Content (Join-Path $overwriteDir "calibration_registry_snapshot_diff.json") -Raw
    if ($replacedJson -eq "old") { throw "Overwrite must replace known output files" }

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
    $evidenceTamperBefore = Join-Path $invalidFlowRoot "evidence-tamper-before"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $tamperBeforeDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidenceTamperBefore
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Tamper before JSON"
    if ($parsed.before_valid -ne $false) { throw "Tamper before expected before_valid=false" }
    if ($parsed.after_valid -ne $true) { throw "Tamper before expected after_valid=true" }
    if (Test-Path (Join-Path $evidenceTamperBefore "calibration_registry_snapshot_diff.json")) {
        throw "Tamper before must not write evidence pack"
    }

    # Tamper after JSON
    $tamperAfterDir = Copy-Snapshot -Name "tamper-after" -SourceDir $plusOneSnapshotDir
    $taJsonPath = Join-Path $tamperAfterDir "calibration_artifact_registry.json"
    $ta = Get-Content $taJsonPath -Raw | ConvertFrom-Json
    $ta.artifact_count = 999
    $ta | ConvertTo-Json -Depth 10 | Set-Content $taJsonPath -NoNewline
    Add-Content -Path $taJsonPath -Value "" -NoNewline
    $evidenceTamperAfter = Join-Path $invalidFlowRoot "evidence-tamper-after"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $tamperAfterDir,
        "--output-dir", $evidenceTamperAfter
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Tamper after JSON"
    if ($parsed.before_valid -ne $true) { throw "Tamper after expected before_valid=true" }
    if ($parsed.after_valid -ne $false) { throw "Tamper after expected after_valid=false" }
    if (Test-Path (Join-Path $evidenceTamperAfter "calibration_registry_snapshot_diff.json")) {
        throw "Tamper after must not write evidence pack"
    }

    # Delete before MD
    $deleteBeforeMdDir = Copy-Snapshot -Name "delete-before-md" -SourceDir $fullSnapshotDir
    Remove-Item (Join-Path $deleteBeforeMdDir "calibration_artifact_registry.md") -Force
    $evidenceDeleteBeforeMd = Join-Path $invalidFlowRoot "evidence-delete-before-md"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $deleteBeforeMdDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidenceDeleteBeforeMd
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Delete before MD"
    if ($parsed.before_valid -ne $false) { throw "Delete before MD expected before_valid=false" }
    if (Test-Path (Join-Path $evidenceDeleteBeforeMd "calibration_registry_snapshot_diff.json")) {
        throw "Delete before MD must not write evidence pack"
    }

    # Delete after SHA256SUMS
    $deleteAfterSumsDir = Copy-Snapshot -Name "delete-after-sums" -SourceDir $plusOneSnapshotDir
    Remove-Item (Join-Path $deleteAfterSumsDir "SHA256SUMS.txt") -Force
    $evidenceDeleteAfterSums = Join-Path $invalidFlowRoot "evidence-delete-after-sums"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $deleteAfterSumsDir,
        "--output-dir", $evidenceDeleteAfterSums
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Delete after SHA256SUMS"
    if ($parsed.after_valid -ne $false) { throw "Delete after SHA256SUMS expected after_valid=false" }
    if (Test-Path (Join-Path $evidenceDeleteAfterSums "calibration_registry_snapshot_diff.json")) {
        throw "Delete after SHA256SUMS must not write evidence pack"
    }

    # Malformed before artifacts = "bad"
    $badArtifactsDir = Copy-Snapshot -Name "bad-artifacts" -SourceDir $fullSnapshotDir
    $baPath = Join-Path $badArtifactsDir "calibration_artifact_registry.json"
    $ba = Get-Content $baPath -Raw | ConvertFrom-Json
    $ba.artifacts = "bad"
    $ba | ConvertTo-Json -Depth 10 | Set-Content $baPath -NoNewline
    Add-Content -Path $baPath -Value "" -NoNewline
    $evidenceBadArtifacts = Join-Path $invalidFlowRoot "evidence-bad-artifacts"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $badArtifactsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidenceBadArtifacts
    )
    Assert-InvalidDiffExportResult -Result $r -Context "Malformed artifacts string" | Out-Null
    if (Test-Path (Join-Path $evidenceBadArtifacts "calibration_registry_snapshot_diff.json")) {
        throw "Malformed artifacts must not write evidence pack"
    }

    # Inject coordinate field into after first artifact
    $coordDir = Copy-Snapshot -Name "coord-injected" -SourceDir $plusOneSnapshotDir
    $cPath = Join-Path $coordDir "calibration_artifact_registry.json"
    $c = Get-Content $cPath -Raw | ConvertFrom-Json
    $c.artifacts[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    $c | ConvertTo-Json -Depth 10 | Set-Content $cPath -NoNewline
    Add-Content -Path $cPath -Value "" -NoNewline
    $evidenceCoord = Join-Path $invalidFlowRoot "evidence-coord"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $coordDir,
        "--output-dir", $evidenceCoord
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Coordinate field injected"
    if ($parsed.after_valid -ne $false) { throw "Coordinate injected expected after_valid=false" }
    if (Test-Path (Join-Path $evidenceCoord "calibration_registry_snapshot_diff.json")) {
        throw "Coordinate injected must not write evidence pack"
    }

    # Inject label payload field into before first artifact
    $labelsDir = Copy-Snapshot -Name "labels-injected" -SourceDir $fullSnapshotDir
    $lPath = Join-Path $labelsDir "calibration_artifact_registry.json"
    $l = Get-Content $lPath -Raw | ConvertFrom-Json
    $l.artifacts[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    $l | ConvertTo-Json -Depth 10 | Set-Content $lPath -NoNewline
    Add-Content -Path $lPath -Value "" -NoNewline
    $evidenceLabels = Join-Path $invalidFlowRoot "evidence-labels"
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $labelsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidenceLabels
    )
    $parsed = Assert-InvalidDiffExportResult -Result $r -Context "Label payload field injected"
    if ($parsed.before_valid -ne $false) { throw "Labels injected expected before_valid=false" }
    if (Test-Path (Join-Path $evidenceLabels "calibration_registry_snapshot_diff.json")) {
        throw "Labels injected must not write evidence pack"
    }

    # ============================================================
    # INVALID MARKDOWN SMOKE
    # ============================================================
    $invalidMdExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $badArtifactsDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", (Join-Path $invalidFlowRoot "evidence-invalid-md"),
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $invalidMdExportResult.StdErr -Context "Invalid markdown diff export"
    if ($invalidMdExportResult.ExitCode -eq 0) { throw "Invalid markdown diff export expected non-zero exit code" }
    $invalidMdOut = $invalidMdExportResult.StdOut
    Assert-TextIncludes -Text $invalidMdOut -Expected "# Calibration Registry Snapshot Diff Export" -Context "Invalid markdown diff export"
    Assert-TextIncludes -Text $invalidMdOut -Expected "Status:" -Context "Invalid markdown diff export"
    Assert-TextIncludes -Text $invalidMdOut -Expected "## Reasons" -Context "Invalid markdown diff export"

    # ============================================================
    # SAFETY: NO FULL LABEL PAYLOAD OR COORDINATE FIELDS
    # ============================================================
    $diffStr = $plusOneDiffExportResult.StdOut
    if ($diffStr.Contains('"labels"')) { throw "Diff export stdout must not contain full label payload field: labels" }
    if ($diffStr.Contains('"label_ids"')) { throw "Diff export stdout must not contain full label payload field: label_ids" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($diffStr.Contains('"' + $coord + '"')) { throw "Diff export stdout must not contain coordinate field: $coord" }
    }

    $mdDiffExportStr = $mdDiffExportOut
    if ($mdDiffExportStr.Contains("labels")) { throw "Markdown diff export stdout must not contain full label payload dump" }
    if ($mdDiffExportStr.Contains("label_ids")) { throw "Markdown diff export stdout must not contain full label payload dump" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($mdDiffExportStr.Contains($coord)) { throw "Markdown diff export stdout must not contain coordinate dump: $coord" }
    }

    # Evidence JSON safety
    $evidenceJsonStr = Get-Content (Join-Path $evidencePlusOne "calibration_registry_snapshot_diff.json") -Raw
    if ($evidenceJsonStr.Contains('"labels"')) { throw "Evidence JSON must not contain full label payload field: labels" }
    if ($evidenceJsonStr.Contains('"label_ids"')) { throw "Evidence JSON must not contain full label payload field: label_ids" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($evidenceJsonStr.Contains('"' + $coord + '"')) { throw "Evidence JSON must not contain coordinate field: $coord" }
    }

    # Evidence markdown safety
    $evidenceMdStr = Get-Content (Join-Path $evidencePlusOne "calibration_registry_snapshot_diff.md") -Raw
    if ($evidenceMdStr.Contains("labels")) { throw "Evidence markdown must not contain full label payload dump" }
    if ($evidenceMdStr.Contains("label_ids")) { throw "Evidence markdown must not contain full label payload dump" }
    foreach ($coord in @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")) {
        if ($evidenceMdStr.Contains($coord)) { throw "Evidence markdown must not contain coordinate dump: $coord" }
    }

    # ============================================================
    # OUTSIDE-CWD SAFETY CHECKS
    # ============================================================
    foreach ($flowRoot in @($readyFlowRoot, $incompleteFlowRoot, $deniedFlowRoot, $registryFlowRoot, $emptyRegistryRoot, $invalidFlowRoot)) {
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

Write-Host "Phase 23 calibration registry snapshot diff export release verification passed."
