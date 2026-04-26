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

function Assert-LabelsDoNotExposeCoordinates {
    param(
        [Parameter(Mandatory = $true)]
        [object[]] $Labels,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $forbiddenFields = @("lon", "lat", "longitude", "latitude", "geometry", "centroid", "bbox")
    foreach ($label in $Labels) {
        foreach ($field in $forbiddenFields) {
            if ($label.PSObject.Properties[$field]) {
                throw "$Context label $($label.candidate_id) unexpectedly includes coordinate field '$field'"
            }
        }
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase15-calibration-label-release-verify-" + [guid]::NewGuid().ToString())
$labelFlowRoot = Join-Path $baseTempRoot "label"
$noReviewFlowRoot = Join-Path $baseTempRoot "no-review"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $labelFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $noReviewFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location
try {
    Set-Location $labelFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $labelFlowRoot "phase15-label.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Label flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase15-label-a-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$createRun.run_id -ne "phase15-label-a-001") {
        throw "Label flow expected run_id=phase15-label-a-001, got $($createRun.run_id)"
    }
    if ([string]$createRun.legal_gate.decision -ne "pass") {
        throw "Label flow expected legal_gate.decision=pass, got $($createRun.legal_gate.decision)"
    }

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase15-label-a-001")
    $candidateCount = [int]$executeRun.candidate_count
    if ($candidateCount -le 0) {
        throw "Label flow expected candidate_count > 0"
    }
    if ($candidateCount -lt 2) {
        throw "Label flow expected at least 2 candidates so both approve_for_archive_quote and watch decisions can be exercised"
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
        "--run-id", "phase15-label-a-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidates = @($reviewQueue)
    if ($reviewCandidates.Count -lt $requiredReviewCount) {
        throw "Label flow expected at least $requiredReviewCount review candidates"
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
            "--run-id", "phase15-label-a-001",
            "--reviewer-id", "phase15-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase15 calibration label smoke approve"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Label flow expected candidate $($candidate.candidate_id) to be approved_for_archive_quote"
        }
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase15-label-a-001",
            "--reviewer-id", "phase15-release-verifier",
            "--decision", "watch",
            "--note", "phase15 calibration label smoke watch"
        )
        if ([string]$decision.candidate.current_state -ne "watch") {
            throw "Label flow expected candidate $($candidate.candidate_id) to move to watch"
        }
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase15-label-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportAuditHash = [string]$exportCreate.audit_manifest.audit_manifest_hash
    if (-not $exportAuditHash) {
        throw "Label flow expected export audit manifest hash"
    }

    $packResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-a-001"
    )
    Assert-NoTraceback -Text $packResult.StdErr -Context "Label flow default calibration-label-pack"
    if ($packResult.ExitCode -ne 0) {
        throw "Label flow default calibration-label-pack failed.`n$($packResult.StdErr)"
    }
    if (-not $packResult.StdOut) {
        throw "Label flow default calibration-label-pack returned empty stdout"
    }
    $pack = $packResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $pack -Fields @(
        "run_id",
        "status",
        "reasons",
        "calibration_policy_id",
        "calibration_policy",
        "processing_baseline_id",
        "score_formula_version",
        "source_scene_manifest_hash",
        "legal_gate",
        "composite_quality",
        "candidate_count",
        "review_state_counts",
        "reviewed_candidate_count",
        "approved_candidate_count",
        "rejected_candidate_count",
        "watched_candidate_count",
        "pending_candidate_count",
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "label_pack_hash",
        "labels"
    ) -Context "Label flow default calibration-label-pack"
    if ([string]$pack.run_id -ne "phase15-label-a-001") {
        throw "Label flow expected run_id=phase15-label-a-001, got $($pack.run_id)"
    }
    if ([string]$pack.status -ne "ready") {
        throw "Label flow expected status=ready, got $($pack.status)"
    }
    if ([string]$pack.legal_gate.decision -ne "pass") {
        throw "Label flow expected legal_gate.decision=pass, got $($pack.legal_gate.decision)"
    }
    if ([string]$pack.calibration_policy_id -ne "calibration_policy_v1_0_default") {
        throw "Label flow expected calibration_policy_id=calibration_policy_v1_0_default, got $($pack.calibration_policy_id)"
    }
    if ([int]$pack.candidate_count -le 0) {
        throw "Label flow expected candidate_count > 0"
    }
    if ([int]$pack.reviewed_candidate_count -le 0) {
        throw "Label flow expected reviewed_candidate_count > 0"
    }
    if ([int]$pack.approved_candidate_count -le 0) {
        throw "Label flow expected approved_candidate_count > 0"
    }
    if ([int]$pack.watched_candidate_count -le 0) {
        throw "Label flow expected watched_candidate_count > 0"
    }
    if ([int]$pack.pending_candidate_count -lt 0) {
        throw "Label flow expected pending_candidate_count >= 0"
    }
    if (-not $pack.review_state_counts.PSObject.Properties["approved_for_archive_quote"]) {
        throw "Label flow expected review_state_counts to include approved_for_archive_quote"
    }
    if (-not $pack.review_state_counts.PSObject.Properties["watch"]) {
        throw "Label flow expected review_state_counts to include watch"
    }
    if ([double]$pack.review_coverage_rate -lt 0.20) {
        throw "Label flow expected review_coverage_rate >= 0.20, got $($pack.review_coverage_rate)"
    }
    if ([double]$pack.top20_review_coverage_rate -lt 0.50) {
        throw "Label flow expected top20_review_coverage_rate >= 0.50, got $($pack.top20_review_coverage_rate)"
    }
    if ($pack.export_audit_ready -ne $true) {
        throw "Label flow expected export_audit_ready=true"
    }
    if (-not [string]$pack.latest_export_audit_manifest_hash) {
        throw "Label flow expected latest_export_audit_manifest_hash to be non-empty"
    }
    if ([string]$pack.latest_export_audit_manifest_hash -ne $exportAuditHash) {
        throw "Label flow expected latest_export_audit_manifest_hash to equal export audit manifest hash"
    }
    if (-not [string]$pack.label_pack_hash) {
        throw "Label flow expected label_pack_hash to be non-empty"
    }
    $defaultLabels = @($pack.labels)
    if ($defaultLabels.Count -le 0) {
        throw "Label flow expected labels to be non-empty"
    }
    foreach ($label in $defaultLabels) {
        if ([string]$label.review_state -eq "pending_review") {
            throw "Label flow expected default labels to exclude pending_review entries"
        }
        Assert-JsonFieldsPresent -Object $label -Fields @(
            "candidate_id",
            "rank",
            "score",
            "review_state",
            "score_formula_version",
            "scoring_explanation"
        ) -Context "Label flow default label entry"
    }
    Assert-LabelsDoNotExposeCoordinates -Labels $defaultLabels -Context "Label flow default labels"

    $packRepeatResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-a-001"
    )
    Assert-NoTraceback -Text $packRepeatResult.StdErr -Context "Label flow repeated calibration-label-pack"
    if ($packRepeatResult.ExitCode -ne 0) {
        throw "Label flow repeated calibration-label-pack failed.`n$($packRepeatResult.StdErr)"
    }
    $packRepeat = $packRepeatResult.StdOut | ConvertFrom-Json
    if ([string]$packRepeat.label_pack_hash -ne [string]$pack.label_pack_hash) {
        throw "Label flow expected repeated label_pack_hash to be identical"
    }
    if (@($packRepeat.labels).Count -ne $defaultLabels.Count) {
        throw "Label flow expected repeated labels count to match default labels count"
    }

    $packPendingResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-a-001",
        "--include-pending"
    )
    Assert-NoTraceback -Text $packPendingResult.StdErr -Context "Label flow include-pending calibration-label-pack"
    if ($packPendingResult.ExitCode -ne 0) {
        throw "Label flow include-pending calibration-label-pack failed.`n$($packPendingResult.StdErr)"
    }
    $packPending = $packPendingResult.StdOut | ConvertFrom-Json
    $pendingLabels = @($packPending.labels)
    if ($pendingLabels.Count -lt $defaultLabels.Count) {
        throw "Label flow expected include-pending labels count >= default labels count"
    }
    if ([int]$packPending.pending_candidate_count -gt 0) {
        $pendingEntries = @($pendingLabels | Where-Object { [string]$_.review_state -eq "pending_review" })
        if ($pendingEntries.Count -le 0) {
            throw "Label flow expected include-pending output to contain pending_review entries when pending_candidate_count > 0"
        }
    }
    $defaultCountsJson = ($pack.review_state_counts | ConvertTo-Json -Compress)
    $pendingCountsJson = ($packPending.review_state_counts | ConvertTo-Json -Compress)
    if ($defaultCountsJson -ne $pendingCountsJson) {
        throw "Label flow expected include-pending review_state_counts to match default output"
    }
    Assert-LabelsDoNotExposeCoordinates -Labels $pendingLabels -Context "Label flow include-pending labels"

    Set-Location $noReviewFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $noReviewFlowRoot "phase15-no-review.sqlite3"

    $noReviewInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($noReviewInit.ExitCode -ne 0) {
        throw "No-review flow init-db failed.`n$($noReviewInit.StdErr)"
    }
    $noReviewCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase15-label-no-review-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$noReviewCreate.legal_gate.decision -ne "pass") {
        throw "No-review flow expected legal_gate.decision=pass"
    }
    $noReviewExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase15-label-no-review-001")
    if ([int]$noReviewExecute.candidate_count -le 0) {
        throw "No-review flow expected candidate_count > 0"
    }

    $noReviewPackResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-no-review-001"
    )
    Assert-NoTraceback -Text $noReviewPackResult.StdErr -Context "No-review flow calibration-label-pack"
    if ($noReviewPackResult.ExitCode -ne 0) {
        throw "No-review flow calibration-label-pack unexpectedly failed.`n$($noReviewPackResult.StdErr)"
    }
    $noReviewPack = $noReviewPackResult.StdOut | ConvertFrom-Json
    if ([string]$noReviewPack.status -ne "incomplete") {
        throw "No-review flow expected status=incomplete, got $($noReviewPack.status)"
    }
    Assert-ReasonsIncludeExact -Reasons @($noReviewPack.reasons) -Expected "No reviewed candidates available for calibration label pack" -Context "No-review flow calibration-label-pack"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewPack.reasons) -ExpectedSubstring "Review coverage rate" -Context "No-review flow calibration-label-pack"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewPack.reasons) -ExpectedSubstring "Top-20 review coverage rate" -Context "No-review flow calibration-label-pack"
    Assert-ReasonsIncludeExact -Reasons @($noReviewPack.reasons) -Expected "Export audit manifest not created yet" -Context "No-review flow calibration-label-pack"
    if (@($noReviewPack.labels).Count -ne 0) {
        throw "No-review flow expected default labels to be empty"
    }

    $noReviewMarkdownResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-no-review-001",
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $noReviewMarkdownResult.StdErr -Context "No-review flow markdown calibration-label-pack"
    if ($noReviewMarkdownResult.ExitCode -ne 0) {
        throw "No-review flow markdown calibration-label-pack unexpectedly failed.`n$($noReviewMarkdownResult.StdErr)"
    }
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "# Calibration Label Pack" -Context "No-review flow markdown calibration-label-pack"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected 'Status: `incomplete`' -Context "No-review flow markdown calibration-label-pack"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "## Reasons" -Context "No-review flow markdown calibration-label-pack"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "## Labels" -Context "No-review flow markdown calibration-label-pack"

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase15-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }
    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase15-label-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreate.ExitCode -eq 0) {
        throw "Denied flow expected create-run to exit non-zero"
    }
    Assert-NoTraceback -Text $deniedCreate.StdErr -Context "Denied flow create-run"

    $deniedPackResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase15-label-denied-001"
    )
    Assert-NoTraceback -Text $deniedPackResult.StdErr -Context "Denied flow calibration-label-pack"
    if ($deniedPackResult.ExitCode -eq 0) {
        throw "Denied flow expected calibration-label-pack to exit non-zero"
    }
    $deniedPack = $deniedPackResult.StdOut | ConvertFrom-Json
    if ([string]$deniedPack.status -ne "fail") {
        throw "Denied flow expected status=fail, got $($deniedPack.status)"
    }
    if ([string]$deniedPack.legal_gate.decision -ne "fail") {
        throw "Denied flow expected legal_gate.decision=fail, got $($deniedPack.legal_gate.decision)"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($deniedPack.reasons) -ExpectedSubstring "Legal gate failed" -Context "Denied flow calibration-label-pack"

    foreach ($flowRoot in @($labelFlowRoot, $noReviewFlowRoot, $deniedFlowRoot)) {
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

Write-Host "Phase 15 calibration label release verification passed."
