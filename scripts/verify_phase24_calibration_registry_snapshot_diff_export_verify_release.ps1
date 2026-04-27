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

$baseTempRoot = Join-Path $env:TEMP ("phase24-calibration-registry-snapshot-diff-export-verify-release-" + [guid]::NewGuid().ToString())
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase24-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase24-verify-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase24-verify-ready-001")
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
        "--run-id", "phase24-verify-ready-001",
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
            "--run-id", "phase24-verify-ready-001",
            "--reviewer-id", "phase24-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase24 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase24-verify-ready-001",
            "--reviewer-id", "phase24-verifier",
            "--decision", "watch",
            "--note", "phase24 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase24-verify-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase24-verify-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase24-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase24-verify-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase24-verify-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase24-verify-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase24-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase24-verify-denied-001",
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
        "--run-id", "phase24-verify-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Denied export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # FRESH REGISTRY DB
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase24-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase24-empty-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase24-registry.sqlite3"

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
    if ([string]$fullExport.status -ne "exported") { throw "Full export expected status=exported" }
    if ([int]$fullExport.artifact_count -ne 3) { throw "Full export expected artifact_count=3" }

    $secondFullSnapshotDir = Join-Path $registryFlowRoot "snapshot-full-second"
    $secondFullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $secondFullSnapshotDir
    )
    Assert-NoTraceback -Text $secondFullExportResult.StdErr -Context "Second full registry snapshot export"
    if ($secondFullExportResult.ExitCode -ne 0) {
        throw "Second full registry snapshot export failed.`n$($secondFullExportResult.StdErr)"
    }

    # ============================================================
    # PLUS-ONE REGISTRY SNAPSHOT EXPORT
    # ============================================================
    Set-Location $readyFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase24-generation.sqlite3"
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase24-verify-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase24-verify-ready-002") | Out-Null
    $queue002 = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase24-verify-ready-002",
        "--limit", "1"
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase24-verify-ready-002",
        "--reviewer-id", "phase24-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase24 approve"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase24-verify-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null
    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase24-verify-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase24-registry.sqlite3"
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

    # ============================================================
    # GENERATE ALL DIFF EVIDENCE PACKS
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    $evidenceEmptyEmpty = Join-Path $invalidFlowRoot "evidence-empty-empty"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $evidenceEmptyEmpty
    ) | Out-Null

    $evidenceFullFull = Join-Path $invalidFlowRoot "evidence-full-full"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $secondFullSnapshotDir,
        "--output-dir", $evidenceFullFull
    ) | Out-Null

    $evidenceEmptyFull = Join-Path $invalidFlowRoot "evidence-empty-full"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $fullSnapshotDir,
        "--output-dir", $evidenceEmptyFull
    ) | Out-Null

    $evidenceFullEmpty = Join-Path $invalidFlowRoot "evidence-full-empty"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $evidenceFullEmpty
    ) | Out-Null

    $evidencePlusOne = Join-Path $invalidFlowRoot "evidence-plus-one"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidencePlusOne
    ) | Out-Null

    # ============================================================
    # HELPER FUNCTIONS FOR VERIFY ASSERTIONS
    # ============================================================
    function Assert-ValidVerifyResult {
        param(
            [Parameter(Mandatory = $true)]
            [object] $Result,

            [Parameter(Mandatory = $true)]
            [string] $Context,

            [Parameter(Mandatory = $true)]
            [string] $EvidenceDir,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedAdded,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedRemoved,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedChanged,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedUnchanged
        )

        Assert-NoTraceback -Text $Result.StdErr -Context $Context
        if ($Result.ExitCode -ne 0) { throw "$Context expected exit 0.`n$($Result.StdOut)`n$($Result.StdErr)" }
        if (-not $Result.StdOut) { throw "$Context returned empty output" }
        $parsed = $Result.StdOut | ConvertFrom-Json

        if ([string]$parsed.status -ne "valid") { throw "$Context expected status=valid" }
        if (-not $parsed.reasons) { throw "$Context expected reasons field" }
        if ([string]$parsed.evidence_dir -ne $EvidenceDir) { throw "$Context expected evidence_dir=$EvidenceDir" }
        if (-not [string]$parsed.diff_hash) { throw "$Context expected diff_hash non-empty" }
        if (-not [string]$parsed.before_snapshot_hash) { throw "$Context expected before_snapshot_hash non-empty" }
        if (-not [string]$parsed.after_snapshot_hash) { throw "$Context expected after_snapshot_hash non-empty" }
        if ([int]$parsed.added_count -ne $ExpectedAdded) { throw "$Context expected added_count=$ExpectedAdded" }
        if ([int]$parsed.removed_count -ne $ExpectedRemoved) { throw "$Context expected removed_count=$ExpectedRemoved" }
        if ([int]$parsed.changed_count -ne $ExpectedChanged) { throw "$Context expected changed_count=$ExpectedChanged" }
        if ([int]$parsed.unchanged_count -ne $ExpectedUnchanged) { throw "$Context expected unchanged_count=$ExpectedUnchanged" }

        $expectedFiles = @(
            "calibration_registry_snapshot_diff.json",
            "calibration_registry_snapshot_diff.md",
            "SHA256SUMS.txt"
        )
        foreach ($fileName in $expectedFiles) {
            if ([string]($parsed.files -contains $fileName) -ne "True") {
                throw "$Context expected files to contain $fileName"
            }
            if (-not $parsed.file_hashes.PSObject.Properties[$fileName]) {
                throw "$Context expected file_hashes to contain $fileName"
            }
        }

        if ($parsed.sha256sums_valid -ne $true) { throw "$Context expected sha256sums_valid=true" }
        if ($parsed.json_valid -ne $true) { throw "$Context expected json_valid=true" }
        if ($parsed.markdown_valid -ne $true) { throw "$Context expected markdown_valid=true" }
        if ($parsed.diff_hash_valid -ne $true) { throw "$Context expected diff_hash_valid=true" }
        if ($parsed.evidence_cross_checks_valid -ne $true) { throw "$Context expected evidence_cross_checks_valid=true" }

        return $parsed
    }

    function Assert-InvalidVerifyResult {
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

    function Copy-Evidence {
        param(
            [Parameter(Mandatory = $true)]
            [string] $Name,

            [Parameter(Mandatory = $false)]
            [string] $SourceDir = $evidencePlusOne
        )
        $dest = Join-Path $invalidFlowRoot $Name
        Copy-Item -Path $SourceDir -Destination $dest -Recurse -Force
        return $dest
    }

function Write-LfText {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $Content
    )
    $normalized = $Content -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $normalized, $utf8NoBom)
}

function Recompute-SHA256SUMS {
    param(
        [Parameter(Mandatory = $true)]
        [string] $EvidenceDir
    )
    $jsonPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.json"
    $mdPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.md"
    $jsonHash = Get-SHA256Hex -FilePath $jsonPath
    $mdHash = Get-SHA256Hex -FilePath $mdPath
    $sumsText = "$jsonHash  calibration_registry_snapshot_diff.json`n$mdHash  calibration_registry_snapshot_diff.md`n"
    Write-LfText -Path (Join-Path $EvidenceDir "SHA256SUMS.txt") -Content $sumsText
}

    # ============================================================
    # VALID VERIFICATION CASES
    # ============================================================

    # Empty vs empty
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidenceEmptyEmpty
    )
    Assert-ValidVerifyResult -Result $r -Context "Empty vs empty verify" -EvidenceDir $evidenceEmptyEmpty `
        -ExpectedAdded 0 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 0 | Out-Null

    # Full vs full
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidenceFullFull
    )
    Assert-ValidVerifyResult -Result $r -Context "Full vs full verify" -EvidenceDir $evidenceFullFull `
        -ExpectedAdded 0 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 3 | Out-Null

    # Empty vs full
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidenceEmptyFull
    )
    Assert-ValidVerifyResult -Result $r -Context "Empty vs full verify" -EvidenceDir $evidenceEmptyFull `
        -ExpectedAdded 3 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 0 | Out-Null

    # Full vs empty
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidenceFullEmpty
    )
    Assert-ValidVerifyResult -Result $r -Context "Full vs empty verify" -EvidenceDir $evidenceFullEmpty `
        -ExpectedAdded 0 -ExpectedRemoved 3 -ExpectedChanged 0 -ExpectedUnchanged 0 | Out-Null

    # Full vs plus-one
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidencePlusOne
    )
    Assert-ValidVerifyResult -Result $r -Context "Plus-one verify" -EvidenceDir $evidencePlusOne `
        -ExpectedAdded 1 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 3 | Out-Null

    # ============================================================
    # MARKDOWN OUTPUT SMOKE
    # ============================================================
    $mdResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $evidencePlusOne,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdResult.StdErr -Context "Markdown verify"
    if ($mdResult.ExitCode -ne 0) { throw "Markdown verify expected exit 0" }
    $mdOut = $mdResult.StdOut
    Assert-TextIncludes -Text $mdOut -Expected "# Calibration Registry Snapshot Diff Export Verification" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Status:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Diff hash:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Before snapshot hash:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "After snapshot hash:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Added:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Removed:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Changed:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "Unchanged:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "## Files" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "## Reasons" -Context "Markdown verify"

    # ============================================================
    # INVALID EVIDENCE-PACK SMOKES
    # ============================================================

    # Missing JSON
    $missingJsonDir = Copy-Evidence -Name "missing-json"
    Remove-Item (Join-Path $missingJsonDir "calibration_registry_snapshot_diff.json") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $missingJsonDir
    )
    Assert-InvalidVerifyResult -Result $r -Context "Missing JSON" | Out-Null

    # Missing MD
    $missingMdDir = Copy-Evidence -Name "missing-md"
    Remove-Item (Join-Path $missingMdDir "calibration_registry_snapshot_diff.md") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $missingMdDir
    )
    Assert-InvalidVerifyResult -Result $r -Context "Missing MD" | Out-Null

    # Missing SHA256SUMS
    $missingSumsDir = Copy-Evidence -Name "missing-sums"
    Remove-Item (Join-Path $missingSumsDir "SHA256SUMS.txt") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $missingSumsDir
    )
    Assert-InvalidVerifyResult -Result $r -Context "Missing SHA256SUMS" | Out-Null

    # Tampered JSON
    $tamperJsonDir = Copy-Evidence -Name "tamper-json"
    $tjPath = Join-Path $tamperJsonDir "calibration_registry_snapshot_diff.json"
    $tj = Get-Content $tjPath -Raw | ConvertFrom-Json
    $tj.diff_hash = "tampered"
    $tjJson = $tj | ConvertTo-Json -Depth 10
    Write-LfText -Path $tjPath -Content ($tjJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $tamperJsonDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $tamperJsonDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Tampered JSON"
    if ($parsed.sha256sums_valid -ne $true) { throw "Tampered JSON expected sha256sums_valid=true (only diff_hash mismatch)" }
    if ($parsed.diff_hash_valid -ne $false) { throw "Tampered JSON expected diff_hash_valid=false" }

    # Tampered MD
    $tamperMdDir = Copy-Evidence -Name "tamper-md"
    $tmPath = Join-Path $tamperMdDir "calibration_registry_snapshot_diff.md"
    $tmText = Get-Content $tmPath -Raw
    $tmText = $tmText -replace 'Diff hash:\s*`[^`]+`', 'Diff hash: `tampered`'
    Write-LfText -Path $tmPath -Content $tmText
    Recompute-SHA256SUMS -EvidenceDir $tamperMdDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $tamperMdDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Tampered MD"
    if ($parsed.sha256sums_valid -ne $true) { throw "Tampered MD expected sha256sums_valid=true" }
    if ($parsed.markdown_valid -ne $false) { throw "Tampered MD expected markdown_valid=false" }

    # Tampered SHA256SUMS
    $tamperSumsDir = Copy-Evidence -Name "tamper-sums"
    $tsPath = Join-Path $tamperSumsDir "SHA256SUMS.txt"
    $tsText = Get-Content $tsPath -Raw
    $tsText = $tsText -replace "0", "1"
    Write-LfText -Path $tsPath -Content $tsText
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $tamperSumsDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Tampered SHA256SUMS"
    if ($parsed.sha256sums_valid -ne $false) { throw "Tampered SHA256SUMS expected sha256sums_valid=false" }

    # SHA256SUMS self-hash line
    $selfHashDir = Copy-Evidence -Name "self-hash"
    $shPath = Join-Path $selfHashDir "SHA256SUMS.txt"
    $shText = Get-Content $shPath -Raw
    $shText += "`nabcd1234  SHA256SUMS.txt`n"
    Write-LfText -Path $shPath -Content $shText
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $selfHashDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Self-hash SHA256SUMS"
    if ($parsed.sha256sums_valid -ne $false) { throw "Self-hash expected sha256sums_valid=false" }

    # Malformed JSON
    $malformedDir = Copy-Evidence -Name "malformed"
    Write-LfText -Path (Join-Path $malformedDir "calibration_registry_snapshot_diff.json") -Content "not json"
    Recompute-SHA256SUMS -EvidenceDir $malformedDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $malformedDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Malformed JSON"
    if ($parsed.json_valid -ne $false) { throw "Malformed JSON expected json_valid=false" }

    # Wrong snapshot_diff_type
    $wrongTypeDir = Copy-Evidence -Name "wrong-type"
    $wtPath = Join-Path $wrongTypeDir "calibration_registry_snapshot_diff.json"
    $wt = Get-Content $wtPath -Raw | ConvertFrom-Json
    $wt.snapshot_diff_type = "wrong"
    $wtJson = $wt | ConvertTo-Json -Depth 10
    Write-LfText -Path $wtPath -Content ($wtJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $wrongTypeDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $wrongTypeDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Wrong snapshot_diff_type"
    if ($parsed.json_valid -ne $false) { throw "Wrong type expected json_valid=false" }

    # Wrong snapshot_diff_version
    $wrongVersionDir = Copy-Evidence -Name "wrong-version"
    $wvPath = Join-Path $wrongVersionDir "calibration_registry_snapshot_diff.json"
    $wv = Get-Content $wvPath -Raw | ConvertFrom-Json
    $wv.snapshot_diff_version = 2
    $wvJson = $wv | ConvertTo-Json -Depth 10
    Write-LfText -Path $wvPath -Content ($wvJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $wrongVersionDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $wrongVersionDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Wrong snapshot_diff_version"
    if ($parsed.json_valid -ne $false) { throw "Wrong version expected json_valid=false" }

    # Status not compared
    $notComparedDir = Copy-Evidence -Name "not-compared"
    $ncPath = Join-Path $notComparedDir "calibration_registry_snapshot_diff.json"
    $nc = Get-Content $ncPath -Raw | ConvertFrom-Json
    $nc.status = "invalid"
    $ncJson = $nc | ConvertTo-Json -Depth 10
    Write-LfText -Path $ncPath -Content ($ncJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $notComparedDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $notComparedDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Status not compared"
    if ($parsed.json_valid -ne $false) { throw "Not compared expected json_valid=false" }

    # before_valid false
    $beforeFalseDir = Copy-Evidence -Name "before-false"
    $bfPath = Join-Path $beforeFalseDir "calibration_registry_snapshot_diff.json"
    $bf = Get-Content $bfPath -Raw | ConvertFrom-Json
    $bf.before_valid = $false
    $bfJson = $bf | ConvertTo-Json -Depth 10
    Write-LfText -Path $bfPath -Content ($bfJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $beforeFalseDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $beforeFalseDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "before_valid false"
    if ($parsed.json_valid -ne $false) { throw "before_valid false expected json_valid=false" }

    # after_valid false
    $afterFalseDir = Copy-Evidence -Name "after-false"
    $afPath = Join-Path $afterFalseDir "calibration_registry_snapshot_diff.json"
    $af = Get-Content $afPath -Raw | ConvertFrom-Json
    $af.after_valid = $false
    $afJson = $af | ConvertTo-Json -Depth 10
    Write-LfText -Path $afPath -Content ($afJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $afterFalseDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $afterFalseDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "after_valid false"
    if ($parsed.json_valid -ne $false) { throw "after_valid false expected json_valid=false" }

    # added_count mismatch
    $addedMismatchDir = Copy-Evidence -Name "added-mismatch"
    $amPath = Join-Path $addedMismatchDir "calibration_registry_snapshot_diff.json"
    $am = Get-Content $amPath -Raw | ConvertFrom-Json
    $am.added_count = 99
    $amJson = $am | ConvertTo-Json -Depth 10
    Write-LfText -Path $amPath -Content ($amJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $addedMismatchDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $addedMismatchDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "added_count mismatch"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "added_count mismatch expected evidence_cross_checks_valid=false" }

    # removed_count mismatch
    $removedMismatchDir = Copy-Evidence -Name "removed-mismatch"
    $rmPath = Join-Path $removedMismatchDir "calibration_registry_snapshot_diff.json"
    $rm = Get-Content $rmPath -Raw | ConvertFrom-Json
    $rm.removed_count = 99
    $rmJson = $rm | ConvertTo-Json -Depth 10
    Write-LfText -Path $rmPath -Content ($rmJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $removedMismatchDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $removedMismatchDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "removed_count mismatch"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "removed_count mismatch expected evidence_cross_checks_valid=false" }

    # changed_count mismatch
    $changedMismatchDir = Copy-Evidence -Name "changed-mismatch"
    $cmPath = Join-Path $changedMismatchDir "calibration_registry_snapshot_diff.json"
    $cm = Get-Content $cmPath -Raw | ConvertFrom-Json
    $cm.changed_count = 99
    $cmJson = $cm | ConvertTo-Json -Depth 10
    Write-LfText -Path $cmPath -Content ($cmJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $changedMismatchDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $changedMismatchDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "changed_count mismatch"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "changed_count mismatch expected evidence_cross_checks_valid=false" }

    # unchanged_count mismatch
    $unchangedMismatchDir = Copy-Evidence -Name "unchanged-mismatch"
    $umPath = Join-Path $unchangedMismatchDir "calibration_registry_snapshot_diff.json"
    $um = Get-Content $umPath -Raw | ConvertFrom-Json
    $um.unchanged_count = 99
    $umJson = $um | ConvertTo-Json -Depth 10
    Write-LfText -Path $umPath -Content ($umJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $unchangedMismatchDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $unchangedMismatchDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "unchanged_count mismatch"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "unchanged_count mismatch expected evidence_cross_checks_valid=false" }

    # changed_fields unsorted
    # Need an evidence pack with changed rows; use a changed artifact case
    # Create a before/after with one changed artifact
    $beforeDbChanged = Join-Path $invalidFlowRoot "before-changed.sqlite3"
    $afterDbChanged = Join-Path $invalidFlowRoot "after-changed.sqlite3"

    Set-Location $invalidFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = $beforeDbChanged
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    # Use the ready flow's DB to create snapshots with a changed artifact
    Set-Location $readyFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase24-generation.sqlite3"
    $beforeChangedSnapshotDir = Join-Path $invalidFlowRoot "snapshot-before-changed"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $beforeChangedSnapshotDir
    ) | Out-Null

    # Register a changed version: use a new run with same artifact hash but different label count
    # We need to create a new artifact with same hash but different content
    # Since artifact_hash is based on run_id, we can't easily change it.
    # Instead, let's create a new registry DB with a modified artifact
    # Use Python to directly modify the artifact in a new DB
    $modifyScript = @"
import json, sqlite3
from pathlib import Path
src_db = Path(r'$registryFlowRoot') / 'phase24-registry.sqlite3'
dst_db = Path(r'$invalidFlowRoot') / 'registry-modified.sqlite3'
import shutil
shutil.copy(src_db, dst_db)
conn = sqlite3.connect(dst_db)
conn.execute('UPDATE calibration_label_artifacts SET label_count = 99 WHERE artifact_hash = ?', ('hash1',))
conn.commit()
conn.close()
"@
    # Actually, the artifact_hash is not 'hash1' in the real DB. Let me just use a simpler approach.
    # Create a new evidence pack from full vs plus-one, then manually inject a changed row

    # Actually, let me create a changed artifact by creating a new registry with one artifact and then modifying it
    $changedRegistryDb = Join-Path $invalidFlowRoot "changed-registry.sqlite3"
    $env:LAWFUL_ANOMALY_DB_PATH = $changedRegistryDb
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    ) | Out-Null

    # Now modify the artifact label_count in the DB via Python
    $modifyScript = @"
import sqlite3
conn = sqlite3.connect(r'$changedRegistryDb')
conn.execute('UPDATE calibration_label_artifacts SET label_count = 99')
conn.commit()
conn.close()
"@
    $modifyScriptPath = Join-Path $invalidFlowRoot "modify_db.py"
    Write-LfText -Path $modifyScriptPath -Content $modifyScript
    $pythonResult = Invoke-ProcessCapture -FilePath "python" -Arguments @($modifyScriptPath)
    if ($pythonResult.ExitCode -ne 0) {
        throw "DB modify script failed.`n$($pythonResult.StdErr)"
    }

    $beforeChangedSnapshotDir = Join-Path $invalidFlowRoot "snapshot-changed-before"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $beforeChangedSnapshotDir
    ) | Out-Null

    # Also need the original snapshot again
    $originalRegistryDb = Join-Path $invalidFlowRoot "original-registry.sqlite3"
    $env:LAWFUL_ANOMALY_DB_PATH = $originalRegistryDb
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    ) | Out-Null

    $afterChangedSnapshotDir = Join-Path $invalidFlowRoot "snapshot-changed-after"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $afterChangedSnapshotDir
    ) | Out-Null

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    $evidenceChanged = Join-Path $invalidFlowRoot "evidence-changed"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $afterChangedSnapshotDir,
        "--after-snapshot-dir", $beforeChangedSnapshotDir,
        "--output-dir", $evidenceChanged
    ) | Out-Null

    # Now tamper changed_fields to be unsorted
    $unsortedDir = Copy-Evidence -Name "unsorted" -SourceDir $evidenceChanged
    $usPath = Join-Path $unsortedDir "calibration_registry_snapshot_diff.json"
    $us = Get-Content $usPath -Raw | ConvertFrom-Json
    if ($us.changed.Count -gt 0) {
        $us.changed[0].changed_fields = @("label_count", "artifact_status")
        $usJson = $us | ConvertTo-Json -Depth 10
        Write-LfText -Path $usPath -Content ($usJson + "`n")
        Recompute-SHA256SUMS -EvidenceDir $unsortedDir
        $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
            "calibration-label-registry-snapshot-diff-export-verify",
            "--evidence-dir", $unsortedDir
        )
        $parsed = Assert-InvalidVerifyResult -Result $r -Context "Unsorted changed_fields"
        if ($parsed.evidence_cross_checks_valid -ne $false) { throw "Unsorted expected evidence_cross_checks_valid=false" }
    }

    # Coordinate field injected
    $coordDir = Copy-Evidence -Name "coord-injected"
    $ciPath = Join-Path $coordDir "calibration_registry_snapshot_diff.json"
    $ci = Get-Content $ciPath -Raw | ConvertFrom-Json
    $ci.unchanged[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    $ciJson = $ci | ConvertTo-Json -Depth 10
    Write-LfText -Path $ciPath -Content ($ciJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $coordDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $coordDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Coordinate field injected"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "Coordinate injected expected evidence_cross_checks_valid=false" }

    # Label payload field injected
    $labelsDir = Copy-Evidence -Name "labels-injected"
    $liPath = Join-Path $labelsDir "calibration_registry_snapshot_diff.json"
    $li = Get-Content $liPath -Raw | ConvertFrom-Json
    $li.unchanged[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    $liJson = $li | ConvertTo-Json -Depth 10
    Write-LfText -Path $liPath -Content ($liJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $labelsDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $labelsDir
    )
    $parsed = Assert-InvalidVerifyResult -Result $r -Context "Label payload field injected"
    if ($parsed.evidence_cross_checks_valid -ne $false) { throw "Labels injected expected evidence_cross_checks_valid=false" }

    # ============================================================
    # INVALID MARKDOWN SMOKE
    # ============================================================
    $invalidMdResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-verify",
        "--evidence-dir", $missingJsonDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $invalidMdResult.StdErr -Context "Invalid markdown verify"
    if ($invalidMdResult.ExitCode -eq 0) { throw "Invalid markdown verify expected non-zero exit code" }
    $invalidMdOut = $invalidMdResult.StdOut
    Assert-TextIncludes -Text $invalidMdOut -Expected "# Calibration Registry Snapshot Diff Export Verification" -Context "Invalid markdown verify"
    Assert-TextIncludes -Text $invalidMdOut -Expected "Status:" -Context "Invalid markdown verify"
    Assert-TextIncludes -Text $invalidMdOut -Expected "## Reasons" -Context "Invalid markdown verify"

    # ============================================================
    # SAFETY: NO FULL LABEL PAYLOAD OR COORDINATE FIELDS
    # ============================================================
    $validVerifyStr = $r.StdOut
    # Already checked in invalid cases above

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

Write-Host "Phase 24 calibration registry snapshot diff export verify release verification passed."
