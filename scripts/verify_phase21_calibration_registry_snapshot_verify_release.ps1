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

$baseTempRoot = Join-Path $env:TEMP ("phase21-calibration-registry-snapshot-verify-release-" + [guid]::NewGuid().ToString())
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase21-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase21-snapshot-verify-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase21-snapshot-verify-ready-001")
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
        "--run-id", "phase21-snapshot-verify-ready-001",
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
            "--run-id", "phase21-snapshot-verify-ready-001",
            "--reviewer-id", "phase21-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase21 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase21-snapshot-verify-ready-001",
            "--reviewer-id", "phase21-verifier",
            "--decision", "watch",
            "--note", "phase21 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase21-snapshot-verify-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase21-snapshot-verify-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase21-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase21-snapshot-verify-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase21-snapshot-verify-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase21-snapshot-verify-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase21-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase21-snapshot-verify-denied-001",
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
        "--run-id", "phase21-snapshot-verify-denied-001",
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase21-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase21-empty-registry.sqlite3"

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

    $emptyExport = $emptyExportResult.StdOut | ConvertFrom-Json
    if ([string]$emptyExport.status -ne "exported") { throw "Empty export expected status=exported" }
    if ([int]$emptyExport.artifact_count -ne 0) { throw "Empty export expected artifact_count=0" }
    if (-not [string]$emptyExport.snapshot_hash) { throw "Empty export expected snapshot_hash non-empty" }

    # ============================================================
    # FULL REGISTRY SNAPSHOT EXPORT
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase21-registry.sqlite3"

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

    $expectedFiles = @("calibration_artifact_registry.json", "calibration_artifact_registry.md", "SHA256SUMS.txt")
    $actualFiles = @($fullExport.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Full export expected files list mismatch"
    }

    # ============================================================
    # OFFLINE PROOF: REMOVE DB PATH BEFORE VERIFICATION
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # EMPTY SNAPSHOT VERIFICATION
    # ============================================================
    $emptyVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-verify",
        "--snapshot-dir", $emptySnapshotDir
    )
    Assert-NoTraceback -Text $emptyVerifyResult.StdErr -Context "Empty snapshot verify"
    if ($emptyVerifyResult.ExitCode -ne 0) {
        throw "Empty snapshot verify expected exit 0.`n$($emptyVerifyResult.StdOut)`n$($emptyVerifyResult.StdErr)"
    }
    if (-not $emptyVerifyResult.StdOut) {
        throw "Empty snapshot verify returned empty output"
    }
    $emptyVerify = $emptyVerifyResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $emptyVerify -Fields @(
        "status", "reasons", "snapshot_dir", "artifact_count", "snapshot_hash",
        "files", "file_hashes", "sha256sums_valid", "snapshot_hash_valid", "snapshot_cross_checks_valid"
    ) -Context "Empty verify JSON"
    if ([string]$emptyVerify.status -ne "valid") { throw "Empty verify expected status=valid" }
    if ([int]$emptyVerify.artifact_count -ne 0) { throw "Empty verify expected artifact_count=0" }
    if (-not [string]$emptyVerify.snapshot_hash) { throw "Empty verify expected snapshot_hash non-empty" }
    if ($emptyVerify.sha256sums_valid -ne $true) { throw "Empty verify expected sha256sums_valid=true" }
    if ($emptyVerify.snapshot_hash_valid -ne $true) { throw "Empty verify expected snapshot_hash_valid=true" }
    if ($emptyVerify.snapshot_cross_checks_valid -ne $true) { throw "Empty verify expected snapshot_cross_checks_valid=true" }

    $reasonStrings = @($emptyVerify.reasons | ForEach-Object { [string]$_ })
    if ("Calibration registry snapshot is valid" -notin $reasonStrings) {
        throw "Empty verify expected reasons to include 'Calibration registry snapshot is valid'"
    }
    $actualVerifyFiles = @($emptyVerify.files | ForEach-Object { [string]$_ })
    if (($actualVerifyFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Empty verify expected files list mismatch"
    }
    foreach ($fileName in $expectedFiles) {
        if (-not $emptyVerify.file_hashes.PSObject.Properties[$fileName]) {
            throw "Empty verify file_hashes missing '$fileName'"
        }
    }

    # ============================================================
    # FULL SNAPSHOT VERIFICATION
    # ============================================================
    $fullVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-verify",
        "--snapshot-dir", $fullSnapshotDir
    )
    Assert-NoTraceback -Text $fullVerifyResult.StdErr -Context "Full snapshot verify"
    if ($fullVerifyResult.ExitCode -ne 0) {
        throw "Full snapshot verify expected exit 0.`n$($fullVerifyResult.StdOut)`n$($fullVerifyResult.StdErr)"
    }
    if (-not $fullVerifyResult.StdOut) {
        throw "Full snapshot verify returned empty output"
    }
    $fullVerify = $fullVerifyResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $fullVerify -Fields @(
        "status", "reasons", "snapshot_dir", "artifact_count", "snapshot_hash",
        "files", "file_hashes", "sha256sums_valid", "snapshot_hash_valid", "snapshot_cross_checks_valid"
    ) -Context "Full verify JSON"
    if ([string]$fullVerify.status -ne "valid") { throw "Full verify expected status=valid" }
    if ([int]$fullVerify.artifact_count -ne 3) { throw "Full verify expected artifact_count=3" }
    if (-not [string]$fullVerify.snapshot_hash) { throw "Full verify expected snapshot_hash non-empty" }
    if ($fullVerify.sha256sums_valid -ne $true) { throw "Full verify expected sha256sums_valid=true" }
    if ($fullVerify.snapshot_hash_valid -ne $true) { throw "Full verify expected snapshot_hash_valid=true" }
    if ($fullVerify.snapshot_cross_checks_valid -ne $true) { throw "Full verify expected snapshot_cross_checks_valid=true" }

    $fullReasonStrings = @($fullVerify.reasons | ForEach-Object { [string]$_ })
    if ("Calibration registry snapshot is valid" -notin $fullReasonStrings) {
        throw "Full verify expected reasons to include 'Calibration registry snapshot is valid'"
    }
    $actualFullVerifyFiles = @($fullVerify.files | ForEach-Object { [string]$_ })
    if (($actualFullVerifyFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Full verify expected files list mismatch"
    }
    foreach ($fileName in $expectedFiles) {
        if (-not $fullVerify.file_hashes.PSObject.Properties[$fileName]) {
            throw "Full verify file_hashes missing '$fileName'"
        }
    }

    # ============================================================
    # SNAPSHOT FILE CROSS-CHECKS
    # ============================================================
    $jsonPath = Join-Path $fullSnapshotDir "calibration_artifact_registry.json"
    $mdPath = Join-Path $fullSnapshotDir "calibration_artifact_registry.md"
    $sumsPath = Join-Path $fullSnapshotDir "SHA256SUMS.txt"

    $jsonText = Get-Content $jsonPath -Raw
    $mdText = Get-Content $mdPath -Raw
    $sumsText = Get-Content $sumsPath -Raw

    $fullJson = $jsonText | ConvertFrom-Json
    if ([string]$fullJson.snapshot_type -ne "calibration_artifact_registry") { throw "JSON snapshot_type expected calibration_artifact_registry" }
    if ([int]$fullJson.snapshot_version -ne 1) { throw "JSON snapshot_version expected 1" }
    if ([int]$fullJson.artifact_count -ne 3) { throw "JSON artifact_count expected 3" }
    if ([string]$fullJson.snapshot_hash -ne [string]$fullVerify.snapshot_hash) { throw "JSON snapshot_hash mismatch with verify output" }

    $artifacts = @($fullJson.artifacts)
    $expectedRunIds = @("phase21-snapshot-verify-denied-001", "phase21-snapshot-verify-incomplete-001", "phase21-snapshot-verify-ready-001")
    $actualRunIds = @($artifacts | ForEach-Object { [string]$_.run_id })
    if (($actualRunIds | ConvertTo-Json -Compress) -ne ($expectedRunIds | ConvertTo-Json -Compress)) {
        throw "JSON artifacts run_id order expected: $($expectedRunIds -join ', ')"
    }

    $actualSortKeys = @(
        $artifacts | ForEach-Object {
            [pscustomobject]@{
                run_id = [string]$_.run_id
                artifact_hash = [string]$_.artifact_hash
            }
        }
    )
    $sortedSortKeys = @($actualSortKeys | Sort-Object -Property run_id, artifact_hash)
    if (($actualSortKeys | ConvertTo-Json -Compress) -ne ($sortedSortKeys | ConvertTo-Json -Compress)) {
        throw "JSON artifacts expected to be sorted by run_id ascending, then artifact_hash ascending"
    }

    $artifactStatuses = @($artifacts | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $artifactStatuses -or "incomplete" -notin $artifactStatuses -or "fail" -notin $artifactStatuses) {
        throw "JSON artifacts expected to include ready, incomplete, fail statuses"
    }

    foreach ($artifact in $artifacts) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @(
            "artifact_hash", "run_id", "artifact_status", "label_pack_hash",
            "label_manifest_hash", "label_count", "include_pending", "files", "file_hashes"
        ) -Context "JSON artifact entry"
        if ($artifact.PSObject.Properties["labels"]) { throw "JSON artifact should not include labels" }
        if ($artifact.PSObject.Properties["label_ids"]) { throw "JSON artifact should not include label_ids" }
        if ($artifact.PSObject.Properties["lon"] -or $artifact.PSObject.Properties["lat"] -or $artifact.PSObject.Properties["longitude"] -or $artifact.PSObject.Properties["latitude"] -or $artifact.PSObject.Properties["geometry"] -or $artifact.PSObject.Properties["centroid"] -or $artifact.PSObject.Properties["bbox"]) {
            throw "JSON artifact should not include coordinate fields"
        }
    }

    # ============================================================
    # MARKDOWN STDOUT SMOKE
    # ============================================================
    $mdVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-verify",
        "--snapshot-dir", $fullSnapshotDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdVerifyResult.StdErr -Context "Markdown verify"
    if ($mdVerifyResult.ExitCode -ne 0) {
        throw "Markdown verify expected exit 0.`n$($mdVerifyResult.StdErr)"
    }
    $mdVerifyOut = $mdVerifyResult.StdOut
    Assert-TextIncludes -Text $mdVerifyOut -Expected "# Calibration Registry Snapshot Verification" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected 'Status: `valid`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected 'Snapshot hash valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected 'SHA256SUMS valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected 'Cross-check valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected "Artifact count:" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdVerifyOut -Expected "## Reasons" -Context "Markdown verify"

    # ============================================================
    # INVALID SNAPSHOT SMOKES
    # ============================================================
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
        $hasBadFlag = ($parsed.sha256sums_valid -eq $false) -or ($parsed.snapshot_hash_valid -eq $false) -or ($parsed.snapshot_cross_checks_valid -eq $false)
        $hasReason = ($parsed.reasons.Count -gt 0) -and ($parsed.reasons[0] -ne "Calibration registry snapshot is valid")
        if (-not ($hasBadFlag -or $hasReason)) {
            throw "$Context expected at least one validity flag false or clear malformed reason"
        }
    }

    function Copy-Snapshot {
        param(
            [Parameter(Mandatory = $true)]
            [string] $Name
        )
        $dest = Join-Path $invalidFlowRoot $Name
        Copy-Item -Path $fullSnapshotDir -Destination $dest -Recurse -Force
        return $dest
    }

    # Tamper JSON
    $tamperJsonDir = Copy-Snapshot -Name "tamper-json"
    $tamperJsonPath = Join-Path $tamperJsonDir "calibration_artifact_registry.json"
    $tj = Get-Content $tamperJsonPath -Raw | ConvertFrom-Json
    $tj.artifact_count = 999
    $tj | ConvertTo-Json -Depth 10 | Set-Content $tamperJsonPath -NoNewline
    # ensure trailing newline matches canonical style
    Add-Content -Path $tamperJsonPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $tamperJsonDir)
    Assert-InvalidVerifyResult -Result $r -Context "Tamper JSON"

    # Tamper MD
    $tamperMdDir = Copy-Snapshot -Name "tamper-md"
    $tamperMdPath = Join-Path $tamperMdDir "calibration_artifact_registry.md"
    $tm = Get-Content $tamperMdPath -Raw
    $tm = $tm.Replace("Calibration Registry Snapshot", "TAMPERED")
    Set-Content -Path $tamperMdPath -Value $tm -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $tamperMdDir)
    Assert-InvalidVerifyResult -Result $r -Context "Tamper MD"

    # Tamper SHA256SUMS
    $tamperSumsDir = Copy-Snapshot -Name "tamper-sums"
    $tamperSumsPath = Join-Path $tamperSumsDir "SHA256SUMS.txt"
    $ts = Get-Content $tamperSumsPath -Raw
    $originalTs = $ts
    $match = [regex]::Match($ts, '^([0-9a-f])')
    if (-not $match.Success) {
        throw "Could not find hex hash character in SHA256SUMS.txt"
    }
    $firstHex = $match.Groups[1].Value
    $replacementChar = if ($firstHex -eq '0') { '1' } else { '0' }
    $ts = $ts.Substring(0, $match.Index) + $replacementChar + $ts.Substring($match.Index + 1)
    if ($ts -eq $originalTs) {
        throw "SHA256SUMS tamper did not change content"
    }
    Set-Content -Path $tamperSumsPath -Value $ts -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $tamperSumsDir)
    Assert-InvalidVerifyResult -Result $r -Context "Tamper SHA256SUMS"

    # Delete MD
    $deleteMdDir = Copy-Snapshot -Name "delete-md"
    Remove-Item (Join-Path $deleteMdDir "calibration_artifact_registry.md") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $deleteMdDir)
    Assert-InvalidVerifyResult -Result $r -Context "Delete MD"

    # Malformed artifacts = "bad"
    $badArtifactsDir = Copy-Snapshot -Name "bad-artifacts"
    $baPath = Join-Path $badArtifactsDir "calibration_artifact_registry.json"
    $ba = Get-Content $baPath -Raw | ConvertFrom-Json
    $ba.artifacts = "bad"
    $ba | ConvertTo-Json -Depth 10 | Set-Content $baPath -NoNewline
    Add-Content -Path $baPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $badArtifactsDir)
    Assert-InvalidVerifyResult -Result $r -Context "Malformed artifacts string"

    # Malformed artifacts = ["bad"]
    $badEntryDir = Copy-Snapshot -Name "bad-entry"
    $bePath = Join-Path $badEntryDir "calibration_artifact_registry.json"
    $be = Get-Content $bePath -Raw | ConvertFrom-Json
    $be.artifacts = @("bad")
    $be | ConvertTo-Json -Depth 10 | Set-Content $bePath -NoNewline
    Add-Content -Path $bePath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $badEntryDir)
    Assert-InvalidVerifyResult -Result $r -Context "Malformed artifact entry string"

    # artifact_count non-integer
    $badCountDir = Copy-Snapshot -Name "bad-count"
    $bcPath = Join-Path $badCountDir "calibration_artifact_registry.json"
    $bc = Get-Content $bcPath -Raw | ConvertFrom-Json
    $bc.artifact_count = "99"
    $bc | ConvertTo-Json -Depth 10 | Set-Content $bcPath -NoNewline
    Add-Content -Path $bcPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $badCountDir)
    Assert-InvalidVerifyResult -Result $r -Context "Non-integer artifact_count"

    # Inject coordinate field
    $coordDir = Copy-Snapshot -Name "coord-injected"
    $cPath = Join-Path $coordDir "calibration_artifact_registry.json"
    $c = Get-Content $cPath -Raw | ConvertFrom-Json
    $c.artifacts[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    $c | ConvertTo-Json -Depth 10 | Set-Content $cPath -NoNewline
    Add-Content -Path $cPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $coordDir)
    Assert-InvalidVerifyResult -Result $r -Context "Coordinate field injected"

    # Inject label payload field
    $labelsDir = Copy-Snapshot -Name "labels-injected"
    $lPath = Join-Path $labelsDir "calibration_artifact_registry.json"
    $l = Get-Content $lPath -Raw | ConvertFrom-Json
    $l.artifacts[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    $l | ConvertTo-Json -Depth 10 | Set-Content $lPath -NoNewline
    Add-Content -Path $lPath -Value "" -NoNewline
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $labelsDir)
    Assert-InvalidVerifyResult -Result $r -Context "Label payload field injected"

    # Tamper MD and recompute SHA256SUMS to match tampered markdown
    $tamperMdRecomputeDir = Copy-Snapshot -Name "tamper-md-recompute"
    $tmrMdPath = Join-Path $tamperMdRecomputeDir "calibration_artifact_registry.md"
    $tmrMd = Get-Content $tmrMdPath -Raw
    $tmrMd = $tmrMd.Replace("Registry snapshot exported successfully", "TAMPERED SUCCESS")
    Set-Content -Path $tmrMdPath -Value $tmrMd -NoNewline

    $tmrJsonPath = Join-Path $tamperMdRecomputeDir "calibration_artifact_registry.json"
    $tmrJsonText = Get-Content $tmrJsonPath -Raw
    $jsonHash = (Get-FileHash -Algorithm SHA256 -Path $tmrJsonPath).Hash.ToLowerInvariant()
    $mdHash = (Get-FileHash -Algorithm SHA256 -Path $tmrMdPath).Hash.ToLowerInvariant()
    $newSums = "$jsonHash  calibration_artifact_registry.json`n$mdHash  calibration_artifact_registry.md`n"
    Set-Content -Path (Join-Path $tamperMdRecomputeDir "SHA256SUMS.txt") -Value $newSums -NoNewline

    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-registry-snapshot-verify", "--snapshot-dir", $tamperMdRecomputeDir)
    Assert-InvalidVerifyResult -Result $r -Context "Tamper MD recompute SHA256SUMS"

    # ============================================================
    # INVALID MARKDOWN SMOKE
    # ============================================================
    $invalidMarkdownResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-verify",
        "--snapshot-dir", $badArtifactsDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $invalidMarkdownResult.StdErr -Context "Invalid markdown verify"
    if ($invalidMarkdownResult.ExitCode -eq 0) { throw "Invalid markdown verify expected non-zero exit code" }
    $invalidMdOut = $invalidMarkdownResult.StdOut
    Assert-TextIncludes -Text $invalidMdOut -Expected "# Calibration Registry Snapshot Verification" -Context "Invalid markdown verify"
    Assert-TextIncludes -Text $invalidMdOut -Expected 'Status: `invalid`' -Context "Invalid markdown verify"
    Assert-TextIncludes -Text $invalidMdOut -Expected "## Reasons" -Context "Invalid markdown verify"

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

Write-Host "Phase 21 calibration registry snapshot verify release verification passed."
