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

function Assert-ReasonsIncludeSubstring {
    param(
        [Parameter(Mandatory = $true)]
        [object[]] $Reasons,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedSubstring,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $reasonStrings = @($Reasons | ForEach-Object { [string]$_ })
    if (-not ($reasonStrings | Where-Object { $_ -like "*$ExpectedSubstring*" })) {
        throw "$Context expected reasons to include substring '$ExpectedSubstring'"
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

function Assert-ArtifactFilesAndHashes {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Export,

        [Parameter(Mandatory = $true)]
        [string] $ArtifactDir,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $expectedFiles = @(
        "calibration_label_pack.json",
        "calibration_label_manifest.json",
        "calibration_label_manifest.md",
        "SHA256SUMS.txt"
    )
    $actualFiles = @($Export.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "$Context expected files list to exactly match expected artifact file list"
    }

    foreach ($fileName in $expectedFiles) {
        if (-not $Export.file_hashes.PSObject.Properties[$fileName]) {
            throw "$Context file_hashes missing '$fileName'"
        }
        $artifactPath = Join-Path $ArtifactDir $fileName
        if (-not (Test-Path $artifactPath)) {
            throw "$Context expected artifact file '$artifactPath' to exist"
        }

        [void][System.IO.File]::ReadAllText($artifactPath, [System.Text.Encoding]::UTF8)
        $actualHash = Get-FileSha256Lower -Path $artifactPath
        $reportedHash = [string]$Export.file_hashes.$fileName
        if ($actualHash -ne $reportedHash) {
            throw "$Context expected hash match for '$fileName'"
        }
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase17-calibration-label-artifact-release-verify-" + [guid]::NewGuid().ToString())
$readyFlowRoot = Join-Path $baseTempRoot "ready"
$noReviewFlowRoot = Join-Path $baseTempRoot "no-review"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $readyFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $noReviewFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location
try {
    Set-Location $readyFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase17-label-artifact.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase17-label-artifact-a-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$createRun.run_id -ne "phase17-label-artifact-a-001") {
        throw "Ready flow expected run_id=phase17-label-artifact-a-001, got $($createRun.run_id)"
    }
    if ([string]$createRun.legal_gate.decision -ne "pass") {
        throw "Ready flow expected legal_gate.decision=pass"
    }

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase17-label-artifact-a-001")
    $candidateCount = [int]$executeRun.candidate_count
    if ($candidateCount -le 0) {
        throw "Ready flow expected candidate_count > 0"
    }
    if ($candidateCount -lt 2) {
        throw "Ready flow expected at least 2 candidates"
    }

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
        "--run-id", "phase17-label-artifact-a-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidates = @($reviewQueue)
    if ($reviewCandidates.Count -lt $requiredReviewCount) {
        throw "Ready flow expected at least $requiredReviewCount review candidates"
    }

    $approveCount = [Math]::Max(1, [int][Math]::Floor($requiredReviewCount / 2))
    $watchCount = $requiredReviewCount - $approveCount
    if ($watchCount -lt 1) {
        $watchCount = 1
        $approveCount = $requiredReviewCount - 1
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -First $approveCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase17-label-artifact-a-001",
            "--reviewer-id", "phase17-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase17 artifact approve"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Ready flow expected approved_for_archive_quote for candidate $($candidate.candidate_id)"
        }
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase17-label-artifact-a-001",
            "--reviewer-id", "phase17-release-verifier",
            "--decision", "watch",
            "--note", "phase17 artifact watch"
        )
        if ([string]$decision.candidate.current_state -ne "watch") {
            throw "Ready flow expected watch for candidate $($candidate.candidate_id)"
        }
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase17-label-artifact-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if (-not [string]$exportCreate.audit_manifest.audit_manifest_hash) {
        throw "Ready flow expected export audit manifest hash"
    }

    $artifactDirA = Join-Path $readyFlowRoot "artifact-a"
    $artifactExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-a-001",
        "--output-dir", $artifactDirA
    )
    Assert-NoTraceback -Text $artifactExportResult.StdErr -Context "Ready flow default calibration-label-export"
    if ($artifactExportResult.ExitCode -ne 0) {
        throw "Ready flow default calibration-label-export failed.`n$($artifactExportResult.StdErr)"
    }
    if (-not $artifactExportResult.StdOut) {
        throw "Ready flow default calibration-label-export returned empty stdout"
    }
    $artifactExport = $artifactExportResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $artifactExport -Fields @(
        "run_id",
        "status",
        "reasons",
        "output_dir",
        "include_pending",
        "label_pack_hash",
        "label_manifest_hash",
        "artifact_hash",
        "files",
        "file_hashes"
    ) -Context "Ready flow calibration-label-export"
    if ([string]$artifactExport.run_id -ne "phase17-label-artifact-a-001") {
        throw "Ready flow expected run_id=phase17-label-artifact-a-001"
    }
    if ([string]$artifactExport.status -ne "ready") {
        throw "Ready flow expected status=ready, got $($artifactExport.status)"
    }
    if ($artifactExport.include_pending -ne $false) {
        throw "Ready flow expected include_pending=false"
    }
    if (-not [string]$artifactExport.label_pack_hash) {
        throw "Ready flow expected label_pack_hash non-empty"
    }
    if (-not [string]$artifactExport.label_manifest_hash) {
        throw "Ready flow expected label_manifest_hash non-empty"
    }
    if (-not [string]$artifactExport.artifact_hash) {
        throw "Ready flow expected artifact_hash non-empty"
    }
    if ([string]$artifactExport.output_dir -ne $artifactDirA) {
        throw "Ready flow expected output_dir to equal requested artifact dir"
    }
    Assert-ArtifactFilesAndHashes -Export $artifactExport -ArtifactDir $artifactDirA -Context "Ready flow default calibration-label-export"

    $packJsonPath = Join-Path $artifactDirA "calibration_label_pack.json"
    $manifestJsonPath = Join-Path $artifactDirA "calibration_label_manifest.json"
    $markdownPath = Join-Path $artifactDirA "calibration_label_manifest.md"
    $sumsPath = Join-Path $artifactDirA "SHA256SUMS.txt"
    $pack = Get-Content -Path $packJsonPath -Raw -Encoding utf8 | ConvertFrom-Json
    $manifest = Get-Content -Path $manifestJsonPath -Raw -Encoding utf8 | ConvertFrom-Json
    $markdown = Get-Content -Path $markdownPath -Raw -Encoding utf8
    $checksums = Get-Content -Path $sumsPath -Raw -Encoding utf8

    Assert-TextIncludes -Text $markdown -Expected "# Calibration Label Artifact Export" -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected 'Status: `ready`' -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected "Label pack hash:" -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected "Label manifest hash:" -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected "Artifact hash:" -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected "## Files" -Context "Ready flow calibration_label_manifest.md"
    Assert-TextIncludes -Text $markdown -Expected "## Reasons" -Context "Ready flow calibration_label_manifest.md"

    foreach ($fileName in @("calibration_label_pack.json", "calibration_label_manifest.json", "calibration_label_manifest.md")) {
        $expectedLine = "$([string]$artifactExport.file_hashes.$fileName)  $fileName"
        Assert-TextIncludes -Text $checksums -Expected $expectedLine -Context "Ready flow SHA256SUMS.txt"
    }
    if ($checksums -match "(?m)^.+\s+SHA256SUMS\.txt\s*$") {
        throw "Ready flow SHA256SUMS.txt must not include self-hash line"
    }

    if ([string]$pack.label_pack_hash -ne [string]$artifactExport.label_pack_hash) {
        throw "Ready flow expected pack label_pack_hash to match command output"
    }
    if ([string]$manifest.label_manifest_hash -ne [string]$artifactExport.label_manifest_hash) {
        throw "Ready flow expected manifest label_manifest_hash to match command output"
    }
    if ([string]$manifest.status -ne "ready") {
        throw "Ready flow expected manifest status=ready"
    }
    if ([string]$manifest.label_pack_hash -ne [string]$artifactExport.label_pack_hash) {
        throw "Ready flow expected manifest label_pack_hash to match command output"
    }

    $forbiddenCoordinateFields = @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")
    foreach ($label in @($pack.labels)) {
        foreach ($field in $forbiddenCoordinateFields) {
            if ($label.PSObject.Properties[$field]) {
                throw "Ready flow expected labels to exclude coordinate field '$field'"
            }
        }
    }

    $artifactExportRepeatResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-a-001",
        "--output-dir", $artifactDirA
    )
    Assert-NoTraceback -Text $artifactExportRepeatResult.StdErr -Context "Ready flow repeated calibration-label-export same dir"
    if ($artifactExportRepeatResult.ExitCode -ne 0) {
        throw "Ready flow repeated calibration-label-export same dir failed.`n$($artifactExportRepeatResult.StdErr)"
    }
    $artifactExportRepeat = $artifactExportRepeatResult.StdOut | ConvertFrom-Json
    if ([string]$artifactExportRepeat.artifact_hash -ne [string]$artifactExport.artifact_hash) {
        throw "Ready flow expected repeated same-dir artifact_hash to be identical"
    }
    if ([string]$artifactExportRepeat.label_pack_hash -ne [string]$artifactExport.label_pack_hash) {
        throw "Ready flow expected repeated same-dir label_pack_hash to be identical"
    }
    if ([string]$artifactExportRepeat.label_manifest_hash -ne [string]$artifactExport.label_manifest_hash) {
        throw "Ready flow expected repeated same-dir label_manifest_hash to be identical"
    }
    if (($artifactExportRepeat.file_hashes | ConvertTo-Json -Compress) -ne ($artifactExport.file_hashes | ConvertTo-Json -Compress)) {
        throw "Ready flow expected repeated same-dir file_hashes to be identical"
    }

    $artifactDirB = Join-Path $readyFlowRoot "artifact-b"
    $artifactExportOtherResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-a-001",
        "--output-dir", $artifactDirB
    )
    Assert-NoTraceback -Text $artifactExportOtherResult.StdErr -Context "Ready flow repeated calibration-label-export different dir"
    if ($artifactExportOtherResult.ExitCode -ne 0) {
        throw "Ready flow repeated calibration-label-export different dir failed.`n$($artifactExportOtherResult.StdErr)"
    }
    $artifactExportOther = $artifactExportOtherResult.StdOut | ConvertFrom-Json
    if ([string]$artifactExportOther.output_dir -eq [string]$artifactExport.output_dir) {
        throw "Ready flow expected output_dir to differ for different artifact directory"
    }
    if ([string]$artifactExportOther.artifact_hash -ne [string]$artifactExport.artifact_hash) {
        throw "Ready flow expected different-dir artifact_hash to be identical"
    }
    if (($artifactExportOther.file_hashes | ConvertTo-Json -Compress) -ne ($artifactExport.file_hashes | ConvertTo-Json -Compress)) {
        throw "Ready flow expected different-dir file_hashes to be identical"
    }

    $artifactDirPending = Join-Path $readyFlowRoot "artifact-pending"
    $artifactExportPendingResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-a-001",
        "--output-dir", $artifactDirPending,
        "--include-pending"
    )
    Assert-NoTraceback -Text $artifactExportPendingResult.StdErr -Context "Ready flow include-pending calibration-label-export"
    if ($artifactExportPendingResult.ExitCode -ne 0) {
        throw "Ready flow include-pending calibration-label-export failed.`n$($artifactExportPendingResult.StdErr)"
    }
    $artifactExportPending = $artifactExportPendingResult.StdOut | ConvertFrom-Json
    if ($artifactExportPending.include_pending -ne $true) {
        throw "Ready flow expected include_pending=true for include-pending export"
    }
    Assert-ArtifactFilesAndHashes -Export $artifactExportPending -ArtifactDir $artifactDirPending -Context "Ready flow include-pending calibration-label-export"
    $pendingManifest = Get-Content -Path (Join-Path $artifactDirPending "calibration_label_manifest.json") -Raw -Encoding utf8 | ConvertFrom-Json
    if ([int]$pendingManifest.pending_candidate_count -gt 0 -and [string]$artifactExportPending.artifact_hash -eq [string]$artifactExport.artifact_hash) {
        throw "Ready flow expected include-pending artifact_hash to differ when pending_candidate_count > 0"
    }

    Set-Location $noReviewFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $noReviewFlowRoot "phase17-label-artifact-no-review.sqlite3"

    $noReviewInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($noReviewInit.ExitCode -ne 0) {
        throw "No-review flow init-db failed.`n$($noReviewInit.StdErr)"
    }
    $noReviewCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase17-label-artifact-no-review-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$noReviewCreate.legal_gate.decision -ne "pass") {
        throw "No-review flow expected legal_gate.decision=pass"
    }
    $noReviewExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase17-label-artifact-no-review-001")
    if ([int]$noReviewExecute.candidate_count -le 0) {
        throw "No-review flow expected candidate_count > 0"
    }

    $noReviewArtifactDir = Join-Path $noReviewFlowRoot "artifact"
    $noReviewExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-no-review-001",
        "--output-dir", $noReviewArtifactDir
    )
    Assert-NoTraceback -Text $noReviewExportResult.StdErr -Context "No-review flow calibration-label-export"
    if ($noReviewExportResult.ExitCode -ne 0) {
        throw "No-review flow expected calibration-label-export to exit zero.`n$($noReviewExportResult.StdErr)"
    }
    $noReviewExport = $noReviewExportResult.StdOut | ConvertFrom-Json
    if ([string]$noReviewExport.status -ne "incomplete") {
        throw "No-review flow expected status=incomplete, got $($noReviewExport.status)"
    }
    Assert-ReasonsIncludeExact -Reasons @($noReviewExport.reasons) -Expected "No reviewed candidates available for calibration label pack" -Context "No-review flow calibration-label-export"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewExport.reasons) -ExpectedSubstring "Review coverage rate" -Context "No-review flow calibration-label-export"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewExport.reasons) -ExpectedSubstring "Top-20 review coverage rate" -Context "No-review flow calibration-label-export"
    Assert-ReasonsIncludeExact -Reasons @($noReviewExport.reasons) -Expected "Export audit manifest not created yet" -Context "No-review flow calibration-label-export"
    Assert-ArtifactFilesAndHashes -Export $noReviewExport -ArtifactDir $noReviewArtifactDir -Context "No-review flow calibration-label-export"

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase17-label-artifact-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }
    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase17-label-artifact-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreate.ExitCode -eq 0) {
        throw "Denied flow expected create-run to exit non-zero"
    }
    Assert-NoTraceback -Text $deniedCreate.StdErr -Context "Denied flow create-run"

    $deniedArtifactDir = Join-Path $deniedFlowRoot "artifact"
    $deniedExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase17-label-artifact-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Denied flow calibration-label-export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Denied flow expected calibration-label-export to exit non-zero"
    }
    if (-not $deniedExportResult.StdOut) {
        throw "Denied flow calibration-label-export returned empty stdout"
    }
    $deniedExport = $deniedExportResult.StdOut | ConvertFrom-Json
    if ([string]$deniedExport.status -ne "fail") {
        throw "Denied flow expected status=fail, got $($deniedExport.status)"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($deniedExport.reasons) -ExpectedSubstring "Legal gate failed" -Context "Denied flow calibration-label-export"
    Assert-ArtifactFilesAndHashes -Export $deniedExport -ArtifactDir $deniedArtifactDir -Context "Denied flow calibration-label-export"

    foreach ($flowRoot in @($readyFlowRoot, $noReviewFlowRoot, $deniedFlowRoot)) {
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

    Set-Location $repoRoot
    $repoStatus = (git -C $repoRoot status --porcelain=v1 | Out-String).Trim()
    if ($repoStatus) {
        throw "Repository is not clean after verification.`n$repoStatus"
    }
}
finally {
    Set-Location $originalLocation
}

Write-Host "Phase 17 calibration label artifact release verification passed."
