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

$baseTempRoot = Join-Path $env:TEMP ("phase19-calibration-artifact-registry-release-" + [guid]::NewGuid().ToString())
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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase19-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase19-registry-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase19-registry-ready-001")
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
        "--run-id", "phase19-registry-ready-001",
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
            "--run-id", "phase19-registry-ready-001",
            "--reviewer-id", "phase19-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase19 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase19-registry-ready-001",
            "--reviewer-id", "phase19-verifier",
            "--decision", "watch",
            "--note", "phase19 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase19-registry-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase19-registry-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase19-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase19-registry-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase19-registry-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase19-registry-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase19-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase19-registry-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreateResult.ExitCode -eq 0) {
        throw "Legal-denied create-run expected non-zero exit code"
    }

    $deniedArtifactDir = Join-Path $deniedFlowRoot "artifact-denied"
    $deniedExportResult = Invoke-LawfulJsonAllowFail -Arguments @(
        "calibration-label-export",
        "--run-id", "phase19-registry-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }

    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    # ============================================================
    # FRESH REGISTRY DB PROOF - SEPARATE REGISTRY DATABASE
    # ============================================================
    Set-Location $registryFlowRoot
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase19-registry.sqlite3"

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
    if ([string]$readyRegister.run_id -ne "phase19-registry-ready-001") {
        throw "Ready register expected run_id=phase19-registry-ready-001"
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
    if ([string]$incompleteRegister.run_id -ne "phase19-registry-incomplete-001") {
        throw "Incomplete register expected run_id=phase19-registry-incomplete-001"
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
    if ([string]$deniedRegister.run_id -ne "phase19-registry-denied-001") {
        throw "Denied register expected run_id=phase19-registry-denied-001"
    }

    # ============================================================
    # REGISTRY LIST JSON SMOKE
    # ============================================================
    $registryListResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-list"
    )
    Assert-NoTraceback -Text $registryListResult.StdErr -Context "Registry list"
    if ($registryListResult.ExitCode -ne 0) {
        throw "Registry list failed.`n$($registryListResult.StdErr)"
    }
    $registryList = $registryListResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $registryList -Fields @(
        "status",
        "artifact_count",
        "artifacts"
    ) -Context "Registry list JSON"

    if ([string]$registryList.status -ne "ok") {
        throw "Registry list expected status=ok"
    }
    if ([int]$registryList.artifact_count -ne 3) {
        throw "Registry list expected artifact_count=3"
    }
    $artifacts = @($registryList.artifacts)
    $expectedRunIds = @("phase19-registry-denied-001", "phase19-registry-incomplete-001", "phase19-registry-ready-001")
    $actualRunIds = @($artifacts | ForEach-Object { [string]$_.run_id })
    if (($actualRunIds | ConvertTo-Json -Compress) -ne ($expectedRunIds | ConvertTo-Json -Compress)) {
        throw "Registry list expected artifacts run_id order to be: $($expectedRunIds -join ', ')"
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
        throw "Registry list expected artifacts to be sorted by run_id ascending, then artifact_hash ascending"
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
        ) -Context "Registry list artifact entry"
        if ($artifact.PSObject.Properties["artifact_dir"]) {
            throw "Registry list artifact should not include artifact_dir"
        }
    }

    # ============================================================
    # MARKDOWN OUTPUT SMOKE
    # ============================================================
    $mdRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir,
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdRegisterResult.StdErr -Context "Markdown register"
    if ($mdRegisterResult.ExitCode -ne 0) {
        throw "Markdown register failed.`n$($mdRegisterResult.StdErr)"
    }
    $mdRegOut = $mdRegisterResult.StdOut
    Assert-TextIncludes -Text $mdRegOut -Expected "# Calibration Label Artifact Registration" -Context "Markdown register"
    Assert-TextIncludes -Text $mdRegOut -Expected 'Status: `already_registered`' -Context "Markdown register"
    Assert-TextIncludes -Text $mdRegOut -Expected "Artifact hash:" -Context "Markdown register"
    Assert-TextIncludes -Text $mdRegOut -Expected "Run ID:" -Context "Markdown register"
    Assert-TextIncludes -Text $mdRegOut -Expected "Artifact status:" -Context "Markdown register"
    Assert-TextIncludes -Text $mdRegOut -Expected "## Reasons" -Context "Markdown register"

    $mdListResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-list",
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $mdListResult.StdErr -Context "Markdown list"
    if ($mdListResult.ExitCode -ne 0) {
        throw "Markdown list failed.`n$($mdListResult.StdErr)"
    }
    $mdListOut = $mdListResult.StdOut
    Assert-TextIncludes -Text $mdListOut -Expected "# Calibration Label Artifact Registry" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "Artifact count:" -Context "Markdown list"
    Assert-TextIncludes -Text $mdListOut -Expected "## Artifacts" -Context "Markdown list"

    # ============================================================
    # INVALID ARTIFACT SMOKE (TAMPER)
    # ============================================================
    $tamperDir = Join-Path $tamperFlowRoot "tamper-invalid"
    Copy-Item -Path $readyArtifactDir -Destination $tamperDir -Recurse
    Set-Location $tamperDir
    $sumsFile = Join-Path $tamperDir "SHA256SUMS.txt"
    $sumsContent = Get-Content $sumsFile -Raw
    if ($sumsContent -match '([a-f0-9])') {
        $originalChar = $matches[1]
        $newChar = if ($originalChar -eq 'a') { 'b' } elseif ($originalChar -eq 'b') { 'c' } else { 'A' }
        $sumsContent = $sumsContent -replace $originalChar, $newChar
        Set-Content $sumsFile $sumsContent -NoNewline
    }

    $tamperRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $tamperDir
    )
    Assert-NoTraceback -Text $tamperRegisterResult.StdErr -Context "Tamper register"
    if ($tamperRegisterResult.ExitCode -eq 0) {
        throw "Tamper register expected non-zero exit code"
    }
    $tamperRegister = $tamperRegisterResult.StdOut | ConvertFrom-Json
    if ([string]$tamperRegister.status -ne "invalid") {
        throw "Tamper register expected status=invalid, got $($tamperRegister.status)"
    }
    if ($tamperRegister.PSObject.Properties["registry_record"]) {
        if ($null -ne $tamperRegister.registry_record) {
            throw "Tamper register expected registry_record to be null"
        }
    }

    # Verify registry list still has 3 artifacts
    $registryListAfterTamper = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-list"
    )
    Assert-NoTraceback -Text $registryListAfterTamper.StdErr -Context "Registry list after tamper"
    $registryListAfter = $registryListAfterTamper.StdOut | ConvertFrom-Json
    if ([int]$registryListAfter.artifact_count -ne 3) {
        throw "Registry list after tamper expected artifact_count=3"
    }

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

Write-Host "Phase 19 calibration artifact registry release verification passed."
