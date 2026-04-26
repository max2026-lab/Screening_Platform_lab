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

$baseTempRoot = Join-Path $env:TEMP ("phase18-calibration-label-artifact-verify-release-" + [guid]::NewGuid().ToString())
$readyFlowRoot = Join-Path $baseTempRoot "ready"
$noReviewFlowRoot = Join-Path $baseTempRoot "no-review"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
$tamperFlowRoot = Join-Path $baseTempRoot "tamper"

New-Item -ItemType Directory -Path $readyFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $noReviewFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $tamperFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location
try {
    Set-Location $readyFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase18-verify.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase18-artifact-verify-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase18-artifact-verify-ready-001")
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
        "--run-id", "phase18-artifact-verify-ready-001",
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
            "--run-id", "phase18-artifact-verify-ready-001",
            "--reviewer-id", "phase18-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase18 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase18-artifact-verify-ready-001",
            "--reviewer-id", "phase18-verifier",
            "--decision", "watch",
            "--note", "phase18 watch"
        ) | Out-Null
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase18-artifact-verify-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )

    $artifactDirA = Join-Path $readyFlowRoot "artifact-a"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase18-artifact-verify-ready-001",
        "--output-dir", $artifactDirA
    ) | Out-Null

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    $verifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-verify",
        "--artifact-dir", $artifactDirA
    )
    Assert-NoTraceback -Text $verifyResult.StdErr -Context "Ready flow calibration-label-verify"
    if ($verifyResult.ExitCode -ne 0) {
        throw "Ready flow calibration-label-verify failed.`n$($verifyResult.StdErr)"
    }
    
    $verifyExport = $verifyResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $verifyExport -Fields @(
        "status",
        "reasons",
        "artifact_dir",
        "run_id",
        "label_pack_hash",
        "label_manifest_hash",
        "artifact_hash",
        "files",
        "file_hashes",
        "sha256sums_valid",
        "artifact_hash_valid",
        "label_pack_hash_valid",
        "label_manifest_hash_valid",
        "manifest_cross_checks_valid"
    ) -Context "Ready flow calibration-label-verify JSON"

    if ([string]$verifyExport.status -ne "valid") {
        throw "Ready flow expected status=valid, got $($verifyExport.status)"
    }
    if ([string]$verifyExport.run_id -ne "phase18-artifact-verify-ready-001") {
        throw "Ready flow expected run_id=phase18-artifact-verify-ready-001"
    }
    if (-not [string]$verifyExport.label_pack_hash) {
        throw "Ready flow expected label_pack_hash non-empty"
    }
    if (-not [string]$verifyExport.label_manifest_hash) {
        throw "Ready flow expected label_manifest_hash non-empty"
    }
    if (-not [string]$verifyExport.artifact_hash) {
        throw "Ready flow expected artifact_hash non-empty"
    }
    if ($verifyExport.sha256sums_valid -ne $true) { throw "Ready flow expected sha256sums_valid=true" }
    if ($verifyExport.artifact_hash_valid -ne $true) { throw "Ready flow expected artifact_hash_valid=true" }
    if ($verifyExport.label_pack_hash_valid -ne $true) { throw "Ready flow expected label_pack_hash_valid=true" }
    if ($verifyExport.label_manifest_hash_valid -ne $true) { throw "Ready flow expected label_manifest_hash_valid=true" }
    if ($verifyExport.manifest_cross_checks_valid -ne $true) { throw "Ready flow expected manifest_cross_checks_valid=true" }
    
    Assert-ReasonsIncludeExact -Reasons @($verifyExport.reasons) -Expected "Calibration label artifact is valid" -Context "Ready flow verify reasons"

    $expectedFiles = @("calibration_label_pack.json", "calibration_label_manifest.json", "calibration_label_manifest.md", "SHA256SUMS.txt")
    $actualFiles = @($verifyExport.files | ForEach-Object { [string]$_ })
    if (($actualFiles | ConvertTo-Json -Compress) -ne ($expectedFiles | ConvertTo-Json -Compress)) {
        throw "Ready flow verify expected files list to exactly match expected artifact file list"
    }
    foreach ($fileName in $expectedFiles) {
        if (-not $verifyExport.file_hashes.PSObject.Properties[$fileName]) {
            throw "Ready flow verify file_hashes missing '$fileName'"
        }
    }

    $mdVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-verify",
        "--artifact-dir", $artifactDirA,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdVerifyResult.StdErr -Context "Markdown verify"
    if ($mdVerifyResult.ExitCode -ne 0) { throw "Markdown verify failed.`n$($mdVerifyResult.StdErr)" }
    $mdOut = $mdVerifyResult.StdOut
    Assert-TextIncludes -Text $mdOut -Expected "# Calibration Label Artifact Verification" -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected 'Status: `valid`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected 'Artifact hash valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected 'Label pack hash valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected 'Label manifest hash valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected 'SHA256SUMS valid: `True`' -Context "Markdown verify"
    Assert-TextIncludes -Text $mdOut -Expected "## Reasons" -Context "Markdown verify"

    # Incomplete artifact smoke
    Set-Location $noReviewFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $noReviewFlowRoot "phase18-verify-incomplete.sqlite3"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase18-artifact-verify-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase18-artifact-verify-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $noReviewFlowRoot "artifact"
    $incompleteExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase18-artifact-verify-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    )
    Assert-NoTraceback -Text $incompleteExportResult.StdErr -Context "Incomplete artifact calibration-label-export"
    if ($incompleteExportResult.ExitCode -ne 0) {
        throw "Incomplete artifact calibration-label-export expected exit code 0.`n$($incompleteExportResult.StdErr)"
    }
    if (-not $incompleteExportResult.StdOut) {
        throw "Incomplete artifact calibration-label-export returned empty output"
    }
    
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $incompleteVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-verify",
        "--artifact-dir", $incompleteArtifactDir
    )
    Assert-NoTraceback -Text $incompleteVerifyResult.StdErr -Context "Incomplete verify"
    if ($incompleteVerifyResult.ExitCode -ne 0) {
        throw "Incomplete artifact verify expected calibration-label-verify to exit 0.`n$($incompleteVerifyResult.StdErr)"
    }
    $incompleteVerify = $incompleteVerifyResult.StdOut | ConvertFrom-Json
    if ([string]$incompleteVerify.status -ne "valid") {
        throw "Incomplete artifact verify expected status=valid, got $($incompleteVerify.status)"
    }
    Assert-ReasonsIncludeExact -Reasons @($incompleteVerify.reasons) -Expected "Calibration label artifact is valid" -Context "Incomplete verify"

    # Legal-denied artifact smoke
    Set-Location $deniedFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase18-verify-denied.sqlite3"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $createDeniedResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase18-artifact-verify-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    Assert-NoTraceback -Text $createDeniedResult.StdErr -Context "Legal-denied create-run"
    if ($createDeniedResult.ExitCode -eq 0) {
        throw "Legal-denied create-run expected non-zero exit code"
    }
    if (-not $createDeniedResult.StdOut) {
        throw "Legal-denied create-run returned empty output"
    }

    $deniedArtifactDir = Join-Path $deniedFlowRoot "artifact"
    $deniedExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase18-artifact-verify-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Legal-denied calibration-label-export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }
    if (-not $deniedExportResult.StdOut) {
        throw "Legal-denied calibration-label-export returned empty output"
    }
    
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $deniedVerifyResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-verify",
        "--artifact-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedVerifyResult.StdErr -Context "Denied verify"
    if ($deniedVerifyResult.ExitCode -ne 0) {
        throw "Denied artifact verify expected calibration-label-verify to exit 0.`n$($deniedVerifyResult.StdErr)"
    }
    $deniedVerify = $deniedVerifyResult.StdOut | ConvertFrom-Json
    if ([string]$deniedVerify.status -ne "valid") {
        throw "Denied artifact verify expected status=valid, got $($deniedVerify.status)"
    }

    # Tamper smokes
    function Run-TamperSmoke {
        param(
            [string]$TamperName,
            [scriptblock]$TamperAction
        )
        $targetDir = Join-Path $tamperFlowRoot $TamperName
        Copy-Item -Path $artifactDirA -Destination $targetDir -Recurse
        
        Set-Location $targetDir
        & $TamperAction

        $tamperRes = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("calibration-label-verify", "--artifact-dir", $targetDir)
        Assert-NoTraceback -Text $tamperRes.StdErr -Context "Tamper $TamperName verify"
        if ($tamperRes.ExitCode -eq 0) {
            throw "Tamper $TamperName expected non-zero exit code"
        }
        $tData = $tamperRes.StdOut | ConvertFrom-Json
        if ([string]$tData.status -ne "invalid") {
            throw "Tamper $TamperName expected status=invalid, got $($tData.status)"
        }
        $validityFlags = @($tData.sha256sums_valid, $tData.artifact_hash_valid, $tData.label_pack_hash_valid, $tData.label_manifest_hash_valid, $tData.manifest_cross_checks_valid)
        if ($validityFlags -notcontains $false) {
            $hasReason = $false
            foreach ($r in @($tData.reasons)) {
                if ([string]$r -match "(?i)(coordinate|Missing file|tamper|invalid|fail|hash mismatch)") {
                    $hasReason = $true
                    break
                }
            }
            if (-not $hasReason) {
                throw "Tamper $TamperName expected at least one validity flag false, or reasons clearly explaining the issue.`nGot reasons: $($tData.reasons -join ', ')"
            }
        }
    }

    Run-TamperSmoke -TamperName "tamper-pack" -TamperAction {
        $p = "calibration_label_pack.json"
        $c = Get-Content $p -Raw
        Set-Content $p ($c -replace '}', ' } ') -NoNewline
    }

    Run-TamperSmoke -TamperName "tamper-manifest" -TamperAction {
        $p = "calibration_label_manifest.json"
        $c = Get-Content $p -Raw
        Set-Content $p ($c -replace '}', ' } ') -NoNewline
    }

    Run-TamperSmoke -TamperName "tamper-markdown" -TamperAction {
        $p = "calibration_label_manifest.md"
        Add-Content $p "`nTampered!"
    }

    Run-TamperSmoke -TamperName "tamper-sums" -TamperAction {
        $p = "SHA256SUMS.txt"
        $c = Get-Content $p -Raw
        if ($c -match '([a-f0-9])') {
            $originalChar = $matches[1]
            $newChar = if ($originalChar -eq 'a') { 'b' } elseif ($originalChar -eq 'b') { 'c' } else { 'A' }
            $c = $c -replace $originalChar, $newChar
            Set-Content $p $c -NoNewline
        }
    }

    Run-TamperSmoke -TamperName "delete-markdown" -TamperAction {
        Remove-Item "calibration_label_manifest.md"
    }

    Run-TamperSmoke -TamperName "inject-coord" -TamperAction {
        $p = "calibration_label_pack.json"
        $d = Get-Content $p -Raw | ConvertFrom-Json
        if ($d.labels.Count -gt 0) {
            $d.labels[0] | Add-Member -MemberType NoteProperty -Name "lon" -Value 123.45
            $d | ConvertTo-Json -Depth 10 | Set-Content $p -Encoding utf8

            $newPackHash = Get-FileSha256Lower $p
            $m = "calibration_label_manifest.json"
            $md = Get-Content $m -Raw | ConvertFrom-Json
            $md.label_pack_hash = $newPackHash
            $md | ConvertTo-Json -Depth 10 | Set-Content $m -Encoding utf8

            $newManHash = Get-FileSha256Lower $m
            $s = "SHA256SUMS.txt"
            $sums = Get-Content $s
            $newSums = @()
            foreach ($line in $sums) {
                if ($line -match "calibration_label_pack\.json") {
                    $newSums += "$newPackHash  calibration_label_pack.json"
                } elseif ($line -match "calibration_label_manifest\.json") {
                    $newSums += "$newManHash  calibration_label_manifest.json"
                } else {
                    $newSums += $line
                }
            }
            $newSums | Set-Content $s -Encoding utf8
        }
    }

    foreach ($flowRoot in @($readyFlowRoot, $noReviewFlowRoot, $deniedFlowRoot, $tamperFlowRoot)) {
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

Write-Host "Phase 18 calibration label artifact verify release verification passed."
