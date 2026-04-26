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

function Assert-ReasonsIncludeExact {
    param(
        [Parameter(Mandatory = $true)]
        [object[]] $Reasons,

        [Parameter(Mandatory = $true)]
        [string] $Expected,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $reasonStrings = @($Reasons | ForEach-Object { [string]$_ })
    if ($Expected -notin $reasonStrings) {
        throw "$Context expected reasons to include '$Expected'"
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

function Get-FileSha256Lower {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase20-calibration-registry-snapshot-release-" + [guid]::NewGuid().ToString())
$readyFlowRoot = Join-Path $baseTempRoot "ready"
$incompleteFlowRoot = Join-Path $baseTempRoot "incomplete"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
$registryFlowRoot = Join-Path $baseTempRoot "registry"
$tamperFlowRoot = Join-Path $baseTempRoot "tamper"

New-Item -ItemType Directory -Path $readyFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $incompleteFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $registryFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $tamperFlowRoot -Force | Out-Null

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase20-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase20-snapshot-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase20-snapshot-ready-001")
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
        "--run-id", "phase20-snapshot-ready-001",
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
            "--run-id", "phase20-snapshot-ready-001",
            "--reviewer-id", "phase20-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase20 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase20-snapshot-ready-001",
            "--reviewer-id", "phase20-verifier",
            "--decision", "watch",
            "--note", "phase20 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase20-snapshot-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase20-snapshot-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase20-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase20-snapshot-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase20-snapshot-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase20-snapshot-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase20-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase20-snapshot-denied-001",
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
        "--run-id", "phase20-snapshot-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Denied export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # FRESH REGISTRY DB PROOF - SEPARATE REGISTRY DATABASE
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase20-registry.sqlite3"

    $regInitResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($regInitResult.ExitCode -ne 0) {
        throw "Registry init-db failed.`n$($regInitResult.StdErr)"
    }

    # Register ready artifact
    $readyRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    )
    Assert-NoTraceback -Text $readyRegisterResult.StdErr -Context "Ready register"
    if ($readyRegisterResult.ExitCode -ne 0) {
        throw "Ready register calibration-label-register failed.`n$($readyRegisterResult.StdErr)"
    }
    if (-not $readyRegisterResult.StdOut) {
        throw "Ready register returned empty output"
    }
    $readyRegister = $readyRegisterResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $readyRegister -Fields @(
        "status",
        "reasons",
        "artifact_hash",
        "run_id",
        "artifact_status",
        "label_pack_hash",
        "label_manifest_hash",
        "label_count",
        "include_pending",
        "files",
        "file_hashes",
        "registry_record"
    ) -Context "Ready register JSON"

    if ([string]$readyRegister.status -ne "registered") {
        throw "Ready register expected status=registered, got $($readyRegister.status)"
    }
    if ([string]$readyRegister.run_id -ne "phase20-snapshot-ready-001") {
        throw "Ready register expected run_id=phase20-snapshot-ready-001"
    }
    if ([string]$readyRegister.artifact_status -ne "ready") {
        throw "Ready register expected artifact_status=ready"
    }
    if (-not [string]$readyRegister.artifact_hash) {
        throw "Ready register expected artifact_hash non-empty"
    }
    if (-not [string]$readyRegister.label_pack_hash) {
        throw "Ready register expected label_pack_hash non-empty"
    }
    if (-not [string]$readyRegister.label_manifest_hash) {
        throw "Ready register expected label_manifest_hash non-empty"
    }
    if ([int]$readyRegister.label_count -le 0) {
        throw "Ready register expected label_count > 0"
    }
    if ($readyRegister.include_pending -ne $false) {
        throw "Ready register expected include_pending=false"
    }

    $expectedFiles = @("calibration_label_pack.json", "calibration_label_manifest.json", "calibration_label_manifest.md", "SHA256SUMS.txt")
    $actualFiles = @($readyRegister.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Ready register expected files list to exactly match expected artifact file list"
    }
    foreach ($fileName in $expectedFiles) {
        if (-not $readyRegister.file_hashes.PSObject.Properties[$fileName]) {
            throw "Ready register file_hashes missing '$fileName'"
        }
    }
    if ([string]$readyRegister.registry_record.artifact_hash -ne [string]$readyRegister.artifact_hash) {
        throw "Ready register registry_record.artifact_hash should equal artifact_hash"
    }
    if ([string]$readyRegister.registry_record.run_id -ne [string]$readyRegister.run_id) {
        throw "Ready register registry_record.run_id should equal run_id"
    }
    if ([string]$readyRegister.registry_record.artifact_status -ne [string]$readyRegister.artifact_status) {
        throw "Ready register registry_record.artifact_status should equal artifact_status"
    }
    if ($readyRegister.registry_record.PSObject.Properties["artifact_dir"]) {
        throw "Ready register registry_record should not include artifact_dir"
    }
    if (-not $readyRegister.registry_record.PSObject.Properties["verification"]) {
        throw "Ready register expected registry_record.verification to be present"
    }
    if ($null -eq $readyRegister.registry_record.verification) {
        throw "Ready register expected registry_record.verification to be non-null"
    }
    if ($readyRegister.registry_record.verification.PSObject.Properties["artifact_dir"]) {
        throw "Ready register expected registry_record.verification to not include artifact_dir"
    }

    # Register duplicate - should return already_registered
    $dupRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    )
    Assert-NoTraceback -Text $dupRegisterResult.StdErr -Context "Duplicate register"
    if ($dupRegisterResult.ExitCode -ne 0) {
        throw "Duplicate register failed.`n$($dupRegisterResult.StdErr)"
    }
    $dupRegister = $dupRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$dupRegister.status -ne "already_registered") {
        throw "Duplicate register expected status=already_registered"
    }
    if ([string]$dupRegister.artifact_hash -ne [string]$readyRegister.artifact_hash) {
        throw "Duplicate register artifact_hash should equal first registration"
    }
    if ([string]$dupRegister.registry_record.artifact_hash -ne [string]$dupRegister.artifact_hash) {
        throw "Duplicate register registry_record.artifact_hash should equal artifact_hash"
    }
    if (-not $dupRegister.registry_record.PSObject.Properties["verification"]) {
        throw "Duplicate register expected registry_record.verification to be present"
    }
    if ($null -eq $dupRegister.registry_record.verification) {
        throw "Duplicate register expected registry_record.verification to be non-null"
    }
    if ($dupRegister.registry_record.verification.PSObject.Properties["artifact_dir"]) {
        throw "Duplicate register expected registry_record.verification to not include artifact_dir"
    }

    # Register incomplete artifact
    $incompleteRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $incompleteArtifactDir
    )
    Assert-NoTraceback -Text $incompleteRegisterResult.StdErr -Context "Incomplete register"
    if ($incompleteRegisterResult.ExitCode -ne 0) {
        throw "Incomplete register failed.`n$($incompleteRegisterResult.StdErr)"
    }
    $incompleteRegister = $incompleteRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$incompleteRegister.status -ne "registered") {
        throw "Incomplete register expected status=registered"
    }
    if ([string]$incompleteRegister.artifact_status -ne "incomplete") {
        throw "Incomplete register expected artifact_status=incomplete"
    }
    if ([string]$incompleteRegister.run_id -ne "phase20-snapshot-incomplete-001") {
        throw "Incomplete register expected run_id=phase20-snapshot-incomplete-001"
    }

    # Register denied/fail artifact
    $deniedRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedRegisterResult.StdErr -Context "Denied register"
    if ($deniedRegisterResult.ExitCode -ne 0) {
        throw "Denied register failed.`n$($deniedRegisterResult.StdErr)"
    }
    $deniedRegister = $deniedRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$deniedRegister.status -ne "registered") {
        throw "Denied register expected status=registered"
    }
    if ([string]$deniedRegister.artifact_status -ne "fail") {
        throw "Denied register expected artifact_status=fail"
    }
    if ([string]$deniedRegister.run_id -ne "phase20-snapshot-denied-001") {
        throw "Denied register expected run_id=phase20-snapshot-denied-001"
    }

        # ============================================================
    # EMPTY REGISTRY SNAPSHOT SMOKE
    # ============================================================
    $emptyRegistryRoot = Join-Path $baseTempRoot "empty-registry"
    New-Item -ItemType Directory -Path $emptyRegistryRoot -Force | Out-Null
    Set-Location $emptyRegistryRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase20-empty-registry.sqlite3"

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
    if ([string]$emptyExport.status -ne "exported") {
        throw "Empty registry snapshot expected status=exported, got $($emptyExport.status)"
    }
    if ([int]$emptyExport.artifact_count -ne 0) {
        throw "Empty registry snapshot expected artifact_count=0, got $($emptyExport.artifact_count)"
    }
    if (-not [string]$emptyExport.snapshot_hash) {
        throw "Empty registry snapshot expected snapshot_hash non-empty"
    }

    $expectedFiles = @("calibration_artifact_registry.json", "calibration_artifact_registry.md", "SHA256SUMS.txt")
    $actualFiles = @($emptyExport.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Empty registry snapshot expected files list to exactly match expected artifact file list"
    }

    # ============================================================
    # FULL REGISTRY SNAPSHOT SMOKE
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase20-registry.sqlite3"

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
        "status",
        "reasons",
        "output_dir",
        "artifact_count",
        "snapshot_hash",
        "files",
        "file_hashes"
    ) -Context "Full registry snapshot JSON"

    if ([string]$fullExport.status -ne "exported") { throw "Full registry snapshot expected status=exported" }
    if ([string]$fullExport.output_dir -ne $fullSnapshotDir) { throw "Full registry snapshot expected output_dir=$fullSnapshotDir" }
    if ([int]$fullExport.artifact_count -ne 3) { throw "Full registry snapshot expected artifact_count=3" }
    if (-not [string]$fullExport.snapshot_hash) { throw "Full registry snapshot expected snapshot_hash non-empty" }

    $actualFiles = @($fullExport.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Full registry snapshot expected files list to exactly match expected artifact file list"
    }
    foreach ($fileName in $expectedFiles) {
        if (-not $fullExport.file_hashes.PSObject.Properties[$fileName]) {
            throw "Full registry snapshot file_hashes missing '$fileName'"
        }
        if (-not (Test-Path (Join-Path $fullSnapshotDir $fileName))) {
            throw "Full registry snapshot expected file to exist: $fileName"
        }
    }

    $jsonPath = Join-Path $fullSnapshotDir "calibration_artifact_registry.json"
    $mdPath = Join-Path $fullSnapshotDir "calibration_artifact_registry.md"
    $sumsPath = Join-Path $fullSnapshotDir "SHA256SUMS.txt"

    $jsonText = Get-Content $jsonPath -Raw
    $mdText = Get-Content $mdPath -Raw
    $sumsText = Get-Content $sumsPath -Raw

    Assert-TextIncludes -Text $mdText -Expected "# Calibration Registry Snapshot" -Context "Markdown snapshot"
    Assert-TextIncludes -Text $mdText -Expected "Snapshot hash:" -Context "Markdown snapshot"
    Assert-TextIncludes -Text $mdText -Expected "Artifact count:" -Context "Markdown snapshot"
    Assert-TextIncludes -Text $mdText -Expected "## Files" -Context "Markdown snapshot"
    Assert-TextIncludes -Text $mdText -Expected "## Reasons" -Context "Markdown snapshot"
    Assert-TextIncludes -Text $mdText -Expected "## Artifacts" -Context "Markdown snapshot"

    Assert-TextIncludes -Text $sumsText -Expected "calibration_artifact_registry.json" -Context "SHA256SUMS snapshot"
    Assert-TextIncludes -Text $sumsText -Expected "calibration_artifact_registry.md" -Context "SHA256SUMS snapshot"
    if ($sumsText -match "SHA256SUMS.txt") {
        throw "SHA256SUMS.txt should not include self-hash line"
    }

    $actualJsonHash = Get-FileSha256Lower $jsonPath
    $actualMdHash = Get-FileSha256Lower $mdPath
    $actualSumsHash = Get-FileSha256Lower $sumsPath

    if ([string]$fullExport.file_hashes."calibration_artifact_registry.json" -ne $actualJsonHash) { throw "JSON file_hashes mismatch for json" }
    if ([string]$fullExport.file_hashes."calibration_artifact_registry.md" -ne $actualMdHash) { throw "JSON file_hashes mismatch for md" }
    if ([string]$fullExport.file_hashes."SHA256SUMS.txt" -ne $actualSumsHash) { throw "JSON file_hashes mismatch for sums" }

    if (-not $sumsText.Contains($actualJsonHash)) { throw "SHA256SUMS.txt hash mismatch for json" }
    if (-not $sumsText.Contains($actualMdHash)) { throw "SHA256SUMS.txt hash mismatch for md" }

    $fullJson = $jsonText | ConvertFrom-Json
    if ([string]$fullJson.snapshot_type -ne "calibration_artifact_registry") { throw "JSON snapshot_type expected calibration_artifact_registry" }
    if ([int]$fullJson.snapshot_version -ne 1) { throw "JSON snapshot_version expected 1" }
    if ([int]$fullJson.artifact_count -ne 3) { throw "JSON artifact_count expected 3" }
    if ([string]$fullJson.snapshot_hash -ne [string]$fullExport.snapshot_hash) { throw "JSON snapshot_hash mismatch" }

    $artifacts = @($fullJson.artifacts)
    $expectedRunIds = @("phase20-snapshot-denied-001", "phase20-snapshot-incomplete-001", "phase20-snapshot-ready-001")
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
    $sortedSortKeys = @(
        $actualSortKeys | Sort-Object -Property run_id, artifact_hash
    )
    if (($actualSortKeys | ConvertTo-Json -Compress) -ne ($sortedSortKeys | ConvertTo-Json -Compress)) {
        throw "JSON artifacts expected to be sorted by run_id ascending, then artifact_hash ascending"
    }

    $artifactStatuses = @($artifacts | ForEach-Object { [string]$_.artifact_status })
    if ("ready" -notin $artifactStatuses -or "incomplete" -notin $artifactStatuses -or "fail" -notin $artifactStatuses) {
        throw "JSON artifacts expected to include ready, incomplete, fail statuses"
    }

    foreach ($artifact in $artifacts) {
        Assert-JsonFieldsPresent -Object $artifact -Fields @(
            "artifact_hash",
            "run_id",
            "artifact_status",
            "label_pack_hash",
            "label_manifest_hash",
            "label_count",
            "include_pending",
            "files",
            "file_hashes"
        ) -Context "JSON artifact entry"
        if ($artifact.PSObject.Properties["labels"]) { throw "JSON artifact should not include labels" }
        if ($artifact.PSObject.Properties["label_ids"]) { throw "JSON artifact should not include label_ids" }
        if ($artifact.PSObject.Properties["lon"] -or $artifact.PSObject.Properties["lat"] -or $artifact.PSObject.Properties["longitude"] -or $artifact.PSObject.Properties["latitude"] -or $artifact.PSObject.Properties["geometry"] -or $artifact.PSObject.Properties["centroid"] -or $artifact.PSObject.Properties["bbox"]) {
            throw "JSON artifact should not include coordinate fields"
        }
    }

    # ============================================================
    # DETERMINISM SMOKE
    # ============================================================
    $repeatExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $fullSnapshotDir
    )
    Assert-NoTraceback -Text $repeatExportResult.StdErr -Context "Repeat registry snapshot export"
    $repeatExport = $repeatExportResult.StdOut | ConvertFrom-Json
    if ([string]$repeatExport.snapshot_hash -ne [string]$fullExport.snapshot_hash) { throw "Repeat export snapshot_hash mismatch" }
    foreach ($fileName in $expectedFiles) {
        if ([string]$repeatExport.file_hashes.$fileName -ne [string]$fullExport.file_hashes.$fileName) {
            throw "Repeat export file_hashes mismatch for $fileName"
        }
    }

    $copySnapshotDir = Join-Path $registryFlowRoot "snapshot-copy"
    $copyExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $copySnapshotDir
    )
    Assert-NoTraceback -Text $copyExportResult.StdErr -Context "Copy registry snapshot export"
    $copyExport = $copyExportResult.StdOut | ConvertFrom-Json
    if ([string]$copyExport.output_dir -eq [string]$fullExport.output_dir) { throw "Copy export output_dir should differ" }
    if ([string]$copyExport.snapshot_hash -ne [string]$fullExport.snapshot_hash) { throw "Copy export snapshot_hash mismatch" }
    foreach ($fileName in $expectedFiles) {
        if ([string]$copyExport.file_hashes.$fileName -ne [string]$fullExport.file_hashes.$fileName) {
            throw "Copy export file_hashes mismatch for $fileName"
        }
    }

    # ============================================================
    # INCREMENTAL CHANGE SMOKE
    # ============================================================
    # First generate another ready run
    Set-Location $readyFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase20-generation.sqlite3"
    
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase20-snapshot-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase20-snapshot-ready-002") | Out-Null
    
    # Fast track approval for 1 candidate to export
    $queue002 = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase20-snapshot-ready-002",
        "--limit", "1"
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase20-snapshot-ready-002",
        "--reviewer-id", "phase20-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase20 approve"
    ) | Out-Null

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase20-snapshot-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase20-snapshot-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    # Register it
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase20-registry.sqlite3"
    
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir2
    ) | Out-Null

    # Export snapshot plus one
    $plusOneSnapshotDir = Join-Path $registryFlowRoot "snapshot-plus-one"
    $plusOneExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $plusOneSnapshotDir
    )
    Assert-NoTraceback -Text $plusOneExportResult.StdErr -Context "Plus one registry snapshot export"
    $plusOneExport = $plusOneExportResult.StdOut | ConvertFrom-Json
    if ([int]$plusOneExport.artifact_count -ne 4) { throw "Plus one export expected artifact_count=4" }
    if ([string]$plusOneExport.snapshot_hash -eq [string]$fullExport.snapshot_hash) { throw "Plus one export snapshot_hash should differ" }

    # ============================================================
    # MARKDOWN OUTPUT SMOKE
    # ============================================================
    $mdListResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", (Join-Path $registryFlowRoot "snapshot-md"),
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdListResult.StdErr -Context "Markdown list"
    if ($mdListResult.ExitCode -ne 0) {
        throw "Markdown list failed.`n$($mdListResult.StdErr)"
    }
    $mdListOut = $mdListResult.StdOut
    Assert-TextIncludes -Text $mdListOut -Expected "# Calibration Registry Snapshot" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "Snapshot hash:" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "Artifact count:" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "## Files" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "## Reasons" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "## Artifacts" -Context "Markdown list"

# ============================================================
    # OUTSIDE-CWD SAFETY CHECKS
    # ============================================================
    foreach ($flowRoot in @($readyFlowRoot, $incompleteFlowRoot, $deniedFlowRoot, $registryFlowRoot, $tamperFlowRoot)) {
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

Write-Host "Phase 20 calibration registry snapshot release verification passed."

