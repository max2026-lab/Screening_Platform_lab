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

function Get-SHA256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath
    )
    return (Get-FileHash $FilePath -Algorithm SHA256).Hash.ToLower()
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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase25-calibration-registry-diff-acceptance-gate-release-" + [guid]::NewGuid().ToString())
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase25-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase25-accept-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase25-accept-ready-001")
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
        "--run-id", "phase25-accept-ready-001",
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
            "--run-id", "phase25-accept-ready-001",
            "--reviewer-id", "phase25-accept-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase25 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase25-accept-ready-001",
            "--reviewer-id", "phase25-accept-verifier",
            "--decision", "watch",
            "--note", "phase25 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase25-accept-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase25-accept-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase25-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase25-accept-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase25-accept-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase25-accept-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase25-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase25-accept-denied-001",
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
        "--run-id", "phase25-accept-denied-001",
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase25-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase25-empty-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase25-registry.sqlite3"

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase25-generation.sqlite3"
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase25-accept-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase25-accept-ready-002") | Out-Null
    $queue002 = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase25-accept-ready-002",
        "--limit", "1"
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase25-accept-ready-002",
        "--reviewer-id", "phase25-accept-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase25 approve"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase25-accept-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null
    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase25-accept-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase25-registry.sqlite3"
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
    # CREATE CHANGED EVIDENCE PACK (for rejected changed_count > 0)
    # ============================================================
    $changedRegistryDb = Join-Path $invalidFlowRoot "changed-registry.sqlite3"
    $env:LAWFUL_ANOMALY_DB_PATH = $changedRegistryDb
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    ) | Out-Null

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

    # ============================================================
    # GENERATE ALL DIFF EVIDENCE PACKS
    # ============================================================
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
    # REMOVE DB PATH — ALL ACCEPT COMMANDS RUN OFFLINE
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # HELPER FUNCTIONS FOR ACCEPT ASSERTIONS
    # ============================================================
    function Assert-AcceptedResult {
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

        if ([string]$parsed.status -ne "accepted") { throw "$Context expected status=accepted" }
        if (-not $parsed.reasons) { throw "$Context expected reasons field" }
        if ([string]$parsed.evidence_dir -ne $EvidenceDir) { throw "$Context expected evidence_dir=$EvidenceDir" }
        if ([string]$parsed.policy_id -ne "calibration_registry_diff_acceptance_v1") { throw "$Context expected policy_id=calibration_registry_diff_acceptance_v1" }
        if ([int]$parsed.policy_version -ne 1) { throw "$Context expected policy_version=1" }
        if (-not [string]$parsed.diff_hash) { throw "$Context expected diff_hash non-empty" }
        if (-not [string]$parsed.before_snapshot_hash) { throw "$Context expected before_snapshot_hash non-empty" }
        if (-not [string]$parsed.after_snapshot_hash) { throw "$Context expected after_snapshot_hash non-empty" }
        if ([int]$parsed.added_count -ne $ExpectedAdded) { throw "$Context expected added_count=$ExpectedAdded" }
        if ([int]$parsed.removed_count -ne $ExpectedRemoved) { throw "$Context expected removed_count=$ExpectedRemoved" }
        if ([int]$parsed.changed_count -ne $ExpectedChanged) { throw "$Context expected changed_count=$ExpectedChanged" }
        if ([int]$parsed.unchanged_count -ne $ExpectedUnchanged) { throw "$Context expected unchanged_count=$ExpectedUnchanged" }
        if ($parsed.evidence_valid -ne $true) { throw "$Context expected evidence_valid=true" }
        if ($parsed.sha256sums_valid -ne $true) { throw "$Context expected sha256sums_valid=true" }
        if ($parsed.json_valid -ne $true) { throw "$Context expected json_valid=true" }
        if ($parsed.markdown_valid -ne $true) { throw "$Context expected markdown_valid=true" }
        if ($parsed.diff_hash_valid -ne $true) { throw "$Context expected diff_hash_valid=true" }
        if ($parsed.evidence_cross_checks_valid -ne $true) { throw "$Context expected evidence_cross_checks_valid=true" }
        if (-not [string]$parsed.decision_hash) { throw "$Context expected decision_hash non-empty" }

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

        return $parsed
    }

    function Assert-RejectedResult {
        param(
            [Parameter(Mandatory = $true)]
            [object] $Result,

            [Parameter(Mandatory = $true)]
            [string] $Context,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedRemoved,

            [Parameter(Mandatory = $true)]
            [int] $ExpectedChanged
        )

        Assert-NoTraceback -Text $Result.StdErr -Context $Context
        if ($Result.ExitCode -eq 0) { throw "$Context expected non-zero exit code" }
        if (-not $Result.StdOut) { throw "$Context returned empty output" }
        $parsed = $Result.StdOut | ConvertFrom-Json

        if ([string]$parsed.status -ne "rejected") { throw "$Context expected status=rejected" }
        if ($parsed.evidence_valid -ne $true) { throw "$Context expected evidence_valid=true" }
        if ([int]$parsed.removed_count -ne $ExpectedRemoved) { throw "$Context expected removed_count=$ExpectedRemoved" }
        if ([int]$parsed.changed_count -ne $ExpectedChanged) { throw "$Context expected changed_count=$ExpectedChanged" }
        if (-not [string]$parsed.decision_hash) { throw "$Context expected decision_hash non-empty" }
        if ($parsed.reasons.Count -eq 0) { throw "$Context expected non-empty reasons" }
        return $parsed
    }

    function Assert-InvalidAcceptResult {
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
        if ($parsed.evidence_valid -ne $false) { throw "$Context expected evidence_valid=false" }
        if ($parsed.reasons.Count -eq 0) { throw "$Context expected non-empty reasons" }
        if (-not [string]$parsed.decision_hash) { throw "$Context expected decision_hash non-empty" }
        return $parsed
    }

    # ============================================================
    # ACCEPTED CASES
    # ============================================================

    # Empty vs empty
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceEmptyEmpty
    )
    Assert-AcceptedResult -Result $r -Context "Empty vs empty accept" -EvidenceDir $evidenceEmptyEmpty `
        -ExpectedAdded 0 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 0 | Out-Null

    # Full vs full
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceFullFull
    )
    Assert-AcceptedResult -Result $r -Context "Full vs full accept" -EvidenceDir $evidenceFullFull `
        -ExpectedAdded 0 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 3 | Out-Null

    # Empty vs full
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceEmptyFull
    )
    Assert-AcceptedResult -Result $r -Context "Empty vs full accept" -EvidenceDir $evidenceEmptyFull `
        -ExpectedAdded 3 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 0 | Out-Null

    # Full vs plus-one
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidencePlusOne
    )
    Assert-AcceptedResult -Result $r -Context "Plus-one accept" -EvidenceDir $evidencePlusOne `
        -ExpectedAdded 1 -ExpectedRemoved 0 -ExpectedChanged 0 -ExpectedUnchanged 3 | Out-Null

    # ============================================================
    # REJECTED CASES
    # ============================================================

    # Full vs empty — removed_count > 0
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceFullEmpty
    )
    $rejectedFullEmpty = Assert-RejectedResult -Result $r -Context "Full vs empty accept" `
        -ExpectedRemoved 3 -ExpectedChanged 0
    $hasRemovedReason = $false
    foreach ($reason in $rejectedFullEmpty.reasons) {
        if ($reason -match "removed_count") { $hasRemovedReason = $true }
    }
    if (-not $hasRemovedReason) { throw "Full vs empty accept expected reasons to mention removed_count" }

    # Changed evidence — changed_count > 0
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceChanged
    )
    $rejectedChanged = Assert-RejectedResult -Result $r -Context "Changed accept" `
        -ExpectedRemoved 0 -ExpectedChanged 1
    $hasChangedReason = $false
    foreach ($reason in $rejectedChanged.reasons) {
        if ($reason -match "changed_count") { $hasChangedReason = $true }
    }
    if (-not $hasChangedReason) { throw "Changed accept expected reasons to mention changed_count" }

    # ============================================================
    # INVALID CASES
    # ============================================================

    # Missing JSON
    $missingJsonDir = Copy-Evidence -Name "missing-json" -SourceDir $evidencePlusOne
    Remove-Item (Join-Path $missingJsonDir "calibration_registry_snapshot_diff.json") -Force
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $missingJsonDir
    )
    Assert-InvalidAcceptResult -Result $r -Context "Missing JSON accept" | Out-Null

    # Tampered JSON
    $tamperJsonDir = Copy-Evidence -Name "tamper-json" -SourceDir $evidencePlusOne
    $tjPath = Join-Path $tamperJsonDir "calibration_registry_snapshot_diff.json"
    $tj = Get-Content $tjPath -Raw | ConvertFrom-Json
    $tj.diff_hash = "tampered"
    $tjJson = $tj | ConvertTo-Json -Depth 10
    Write-LfText -Path $tjPath -Content ($tjJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $tamperJsonDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $tamperJsonDir
    )
    Assert-InvalidAcceptResult -Result $r -Context "Tampered JSON accept" | Out-Null

    # Tampered SHA256SUMS
    $tamperSumsDir = Copy-Evidence -Name "tamper-sums" -SourceDir $evidencePlusOne
    $tsPath = Join-Path $tamperSumsDir "SHA256SUMS.txt"
    $tsText = Get-Content $tsPath -Raw
    $tsText = $tsText -replace "0", "1"
    Write-LfText -Path $tsPath -Content $tsText
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $tamperSumsDir
    )
    Assert-InvalidAcceptResult -Result $r -Context "Tampered SHA256SUMS accept" | Out-Null

    # Injected coordinate field
    $coordDir = Copy-Evidence -Name "coord-injected" -SourceDir $evidencePlusOne
    $ciPath = Join-Path $coordDir "calibration_registry_snapshot_diff.json"
    $ci = Get-Content $ciPath -Raw | ConvertFrom-Json
    $ci.unchanged[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    $ciJson = $ci | ConvertTo-Json -Depth 10
    Write-LfText -Path $ciPath -Content ($ciJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $coordDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $coordDir
    )
    Assert-InvalidAcceptResult -Result $r -Context "Coordinate field injected accept" | Out-Null

    # Injected label payload field
    $labelsDir = Copy-Evidence -Name "labels-injected" -SourceDir $evidencePlusOne
    $liPath = Join-Path $labelsDir "calibration_registry_snapshot_diff.json"
    $li = Get-Content $liPath -Raw | ConvertFrom-Json
    $li.unchanged[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    $liJson = $li | ConvertTo-Json -Depth 10
    Write-LfText -Path $liPath -Content ($liJson + "`n")
    Recompute-SHA256SUMS -EvidenceDir $labelsDir
    $r = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $labelsDir
    )
    Assert-InvalidAcceptResult -Result $r -Context "Label payload field injected accept" | Out-Null

    # ============================================================
    # MARKDOWN OUTPUT SMOKES
    # ============================================================

    # Accepted markdown
    $mdAccepted = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidencePlusOne,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdAccepted.StdErr -Context "Markdown accepted"
    if ($mdAccepted.ExitCode -ne 0) { throw "Markdown accepted expected exit 0" }
    $mdOut = $mdAccepted.StdOut
    Assert-TextIncludes -Text $mdOut -Expected "# Calibration Registry Snapshot Diff Acceptance" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Status:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Policy:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Decision hash:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Diff hash:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Before snapshot hash:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "After snapshot hash:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Added:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Removed:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Changed:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "Unchanged:" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "## Files" -Context "Markdown accepted"
    Assert-TextIncludes -Text $mdOut -Expected "## Reasons" -Context "Markdown accepted"

    # Rejected markdown
    $mdRejected = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceFullEmpty,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdRejected.StdErr -Context "Markdown rejected"
    if ($mdRejected.ExitCode -eq 0) { throw "Markdown rejected expected non-zero exit" }
    $mdRejOut = $mdRejected.StdOut
    Assert-TextIncludes -Text $mdRejOut -Expected "# Calibration Registry Snapshot Diff Acceptance" -Context "Markdown rejected"
    Assert-TextIncludes -Text $mdRejOut -Expected "Status:" -Context "Markdown rejected"
    Assert-TextIncludes -Text $mdRejOut -Expected "## Files" -Context "Markdown rejected"
    Assert-TextIncludes -Text $mdRejOut -Expected "## Reasons" -Context "Markdown rejected"

    # Invalid markdown
    $mdInvalid = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $missingJsonDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdInvalid.StdErr -Context "Markdown invalid"
    if ($mdInvalid.ExitCode -eq 0) { throw "Markdown invalid expected non-zero exit" }
    $mdInvOut = $mdInvalid.StdOut
    Assert-TextIncludes -Text $mdInvOut -Expected "# Calibration Registry Snapshot Diff Acceptance" -Context "Markdown invalid"
    Assert-TextIncludes -Text $mdInvOut -Expected "Status:" -Context "Markdown invalid"
    Assert-TextIncludes -Text $mdInvOut -Expected "## Reasons" -Context "Markdown invalid"

    # ============================================================
    # DECISION HASH DETERMINISM
    # ============================================================
    $r1 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceEmptyFull
    )
    if ($r1.ExitCode -ne 0) { throw "Decision hash determinism first run failed" }
    $parsed1 = $r1.StdOut | ConvertFrom-Json
    $hash1 = $parsed1.decision_hash

    $r2 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $evidenceEmptyFull
    )
    if ($r2.ExitCode -ne 0) { throw "Decision hash determinism second run failed" }
    $parsed2 = $r2.StdOut | ConvertFrom-Json
    $hash2 = $parsed2.decision_hash

    if ($hash1 -ne $hash2) { throw "Decision hash not stable across repeated runs on same evidence" }

    # Copy to different path
    $copiedEvidenceDir = Join-Path $invalidFlowRoot "evidence-empty-full-copied"
    Copy-Item -Path $evidenceEmptyFull -Destination $copiedEvidenceDir -Recurse -Force
    $r3 = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export-accept",
        "--evidence-dir", $copiedEvidenceDir
    )
    if ($r3.ExitCode -ne 0) { throw "Decision hash determinism copied run failed" }
    $parsed3 = $r3.StdOut | ConvertFrom-Json
    $hash3 = $parsed3.decision_hash

    if ([string]$parsed3.evidence_dir -eq [string]$parsed1.evidence_dir) {
        throw "Copied evidence expected different evidence_dir"
    }
    if ($hash3 -ne $hash1) { throw "Decision hash not stable across evidence_dir path change" }

    # ============================================================
    # OFFLINE PROOF — DB PATH ALREADY REMOVED ABOVE
    # ============================================================
    if (Test-Path Env:LAWFUL_ANOMALY_DB_PATH) {
        throw "LAWFUL_ANOMALY_DB_PATH must be removed before all accept commands"
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

Write-Host "Phase 25 calibration registry diff acceptance gate release verification passed."
