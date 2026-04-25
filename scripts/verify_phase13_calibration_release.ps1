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

function Assert-CheckNamesPresent {
    param(
        [Parameter(Mandatory = $true)]
        [object[]] $Checks,

        [Parameter(Mandatory = $true)]
        [string[]] $RequiredNames,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $presentNames = @($Checks | ForEach-Object { [string]$_.name })
    foreach ($requiredName in $RequiredNames) {
        if ($requiredName -notin $presentNames) {
            throw "$Context missing check '$requiredName'"
        }
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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase13-calibration-release-verify-" + [guid]::NewGuid().ToString())
$calibrationFlowRoot = Join-Path $baseTempRoot "calibration"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $calibrationFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    Set-Location $calibrationFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $calibrationFlowRoot "phase13-calibration.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Calibration flow init-db failed.`n$($initResult.StdErr)"
    }

    foreach ($runId in @("phase13-calibration-a-001", "phase13-calibration-b-001")) {
        $createRun = Invoke-LawfulJson -Arguments @(
            "create-run",
            "--attestation", "present",
            "--geofence", "clear",
            "--run-id", $runId,
            "--aoi-path", $sampleAoiPath,
            "--start-date", "2024-01-01",
            "--end-date", "2024-03-31"
        )
        if ([string]$createRun.run_id -ne $runId) {
            throw "Calibration flow expected create-run run_id=$runId, got $($createRun.run_id)"
        }
        if ([string]$createRun.legal_gate.decision -ne "pass") {
            throw "Calibration flow expected legal_gate.decision=pass for $runId, got $($createRun.legal_gate.decision)"
        }
    }

    $executeRunA = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase13-calibration-a-001")
    $executeRunB = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase13-calibration-b-001")
    $runACandidateCount = [int]$executeRunA.candidate_count
    $runBCandidateCount = [int]$executeRunB.candidate_count
    if ($runACandidateCount -le 0) {
        throw "Calibration flow expected run A candidate_count > 0"
    }
    if ($runACandidateCount -lt 2) {
        throw "Calibration flow expected at least 2 candidates in run A so both approve_for_archive_quote and watch decisions can be exercised"
    }
    if ($runBCandidateCount -le 0) {
        throw "Calibration flow expected run B candidate_count > 0"
    }

    $topReviewWindow = [Math]::Min($runACandidateCount, 20)
    $requiredReviewCount = [Math]::Max(
        [int][Math]::Ceiling($runACandidateCount * 0.20),
        [int][Math]::Ceiling($topReviewWindow * 0.50)
    )
    if ($requiredReviewCount -lt 2) {
        $requiredReviewCount = 2
    }

    $reviewQueueA = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase13-calibration-a-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidatesA = @($reviewQueueA)
    if ($reviewCandidatesA.Count -lt $requiredReviewCount) {
        throw "Calibration flow expected at least $requiredReviewCount review candidates for run A"
    }

    $approveCount = [Math]::Max(1, [int][Math]::Floor($requiredReviewCount / 2))
    $watchCount = $requiredReviewCount - $approveCount
    if ($watchCount -lt 1) {
        $watchCount = 1
        $approveCount = $requiredReviewCount - 1
    }

    foreach ($candidate in @($reviewCandidatesA | Select-Object -First $approveCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase13-calibration-a-001",
            "--reviewer-id", "phase13-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase13 calibration smoke approve"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Calibration flow expected candidate $($candidate.candidate_id) to be approved_for_archive_quote"
        }
    }

    foreach ($candidate in @($reviewCandidatesA | Select-Object -Skip $approveCount -First $watchCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase13-calibration-a-001",
            "--reviewer-id", "phase13-release-verifier",
            "--decision", "watch",
            "--note", "phase13 calibration smoke watch"
        )
        if ([string]$decision.candidate.current_state -ne "watch") {
            throw "Calibration flow expected candidate $($candidate.candidate_id) to move to watch"
        }
    }

    $exportCreateA = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase13-calibration-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportAuditHash = [string]$exportCreateA.audit_manifest.audit_manifest_hash
    if (-not $exportAuditHash) {
        throw "Calibration flow expected export audit manifest hash for run A"
    }

    $calibrationAResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase13-calibration-a-001",
        "--comparison-run-id", "phase13-calibration-b-001"
    )
    Assert-NoTraceback -Text $calibrationAResult.StdErr -Context "Calibration flow run A calibration-pack"
    if ($calibrationAResult.ExitCode -ne 0) {
        throw "Calibration flow run A calibration-pack failed.`n$($calibrationAResult.StdErr)"
    }
    if (-not $calibrationAResult.StdOut) {
        throw "Calibration flow run A calibration-pack returned empty stdout"
    }
    $calibrationA = $calibrationAResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $calibrationA -Fields @(
        "run_id",
        "status",
        "reasons",
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
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "top20_approval_rate",
        "acceptance_summary",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "paid_escalation_count",
        "reproducibility_summary",
        "calibration_readiness_checks"
    ) -Context "Calibration flow run A calibration-pack"
    if ([string]$calibrationA.run_id -ne "phase13-calibration-a-001") {
        throw "Calibration flow expected run_id=phase13-calibration-a-001, got $($calibrationA.run_id)"
    }
    if ([string]$calibrationA.status -ne "ready") {
        throw "Calibration flow expected status=ready, got $($calibrationA.status)"
    }
    if ([string]$calibrationA.legal_gate.decision -ne "pass") {
        throw "Calibration flow expected legal_gate.decision=pass, got $($calibrationA.legal_gate.decision)"
    }
    if (-not [string]$calibrationA.processing_baseline_id) {
        throw "Calibration flow expected processing_baseline_id to be present"
    }
    if (-not [string]$calibrationA.score_formula_version) {
        throw "Calibration flow expected score_formula_version to be present"
    }
    if ([int]$calibrationA.candidate_count -le 0) {
        throw "Calibration flow expected candidate_count > 0"
    }
    if ([int]$calibrationA.reviewed_candidate_count -le 0) {
        throw "Calibration flow expected reviewed_candidate_count > 0"
    }
    if ([int]$calibrationA.approved_candidate_count -le 0) {
        throw "Calibration flow expected approved_candidate_count > 0"
    }
    if ([int]$calibrationA.watched_candidate_count -le 0) {
        throw "Calibration flow expected watched_candidate_count > 0"
    }
    if ([double]$calibrationA.review_coverage_rate -lt 0.20) {
        throw "Calibration flow expected review_coverage_rate >= 0.20, got $($calibrationA.review_coverage_rate)"
    }
    if ([double]$calibrationA.top20_review_coverage_rate -lt 0.50) {
        throw "Calibration flow expected top20_review_coverage_rate >= 0.50, got $($calibrationA.top20_review_coverage_rate)"
    }
    if ($calibrationA.export_audit_ready -ne $true) {
        throw "Calibration flow expected export_audit_ready=true"
    }
    if (-not [string]$calibrationA.latest_export_audit_manifest_hash) {
        throw "Calibration flow expected latest_export_audit_manifest_hash to be non-empty"
    }
    if ([string]$calibrationA.latest_export_audit_manifest_hash -ne $exportAuditHash) {
        throw "Calibration flow expected latest_export_audit_manifest_hash to equal export audit manifest hash"
    }
    if ($null -eq $calibrationA.reproducibility_summary) {
        throw "Calibration flow expected reproducibility_summary to be present"
    }
    if ([string]$calibrationA.reproducibility_summary.status -ne "pass") {
        throw "Calibration flow expected reproducibility_summary.status=pass, got $($calibrationA.reproducibility_summary.status)"
    }
    if ([double]$calibrationA.reproducibility_summary.top10_stability_rate -ne 1.0) {
        throw "Calibration flow expected reproducibility_summary.top10_stability_rate=1.0, got $($calibrationA.reproducibility_summary.top10_stability_rate)"
    }
    Assert-CheckNamesPresent -Checks @($calibrationA.calibration_readiness_checks) -RequiredNames @(
        "legal_gate",
        "candidate_count",
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "export_audit_ready",
        "reproducibility"
    ) -Context "Calibration flow run A calibration-pack"
    Assert-ReasonsIncludeExact -Reasons @($calibrationA.reasons) -Expected "Calibration readiness checks passed" -Context "Calibration flow run A calibration-pack"

    $calibrationBResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase13-calibration-b-001"
    )
    Assert-NoTraceback -Text $calibrationBResult.StdErr -Context "Calibration flow run B calibration-pack"
    if ($calibrationBResult.ExitCode -ne 0) {
        throw "Calibration flow run B calibration-pack unexpectedly failed.`n$($calibrationBResult.StdErr)"
    }
    if (-not $calibrationBResult.StdOut) {
        throw "Calibration flow run B calibration-pack returned empty stdout"
    }
    $calibrationB = $calibrationBResult.StdOut | ConvertFrom-Json
    if ([string]$calibrationB.status -ne "incomplete") {
        throw "Calibration flow expected run B status=incomplete, got $($calibrationB.status)"
    }
    if ($calibrationB.export_audit_ready -ne $false) {
        throw "Calibration flow expected run B export_audit_ready=false"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($calibrationB.reasons) -ExpectedSubstring "Review coverage rate" -Context "Calibration flow run B calibration-pack"
    Assert-ReasonsIncludeSubstring -Reasons @($calibrationB.reasons) -ExpectedSubstring "Top-20 review coverage rate" -Context "Calibration flow run B calibration-pack"
    Assert-ReasonsIncludeExact -Reasons @($calibrationB.reasons) -Expected "Export audit manifest not created yet" -Context "Calibration flow run B calibration-pack"
    Assert-ReasonsIncludeExact -Reasons @($calibrationB.reasons) -Expected "Reproducibility comparison run not supplied" -Context "Calibration flow run B calibration-pack"

    $markdownBResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase13-calibration-b-001",
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $markdownBResult.StdErr -Context "Calibration flow run B markdown calibration-pack"
    if ($markdownBResult.ExitCode -ne 0) {
        throw "Calibration flow run B markdown calibration-pack unexpectedly failed.`n$($markdownBResult.StdErr)"
    }
    Assert-TextIncludes -Text $markdownBResult.StdOut -Expected "# Calibration Evidence Pack" -Context "Calibration flow run B markdown calibration-pack"
    Assert-TextIncludes -Text $markdownBResult.StdOut -Expected 'Status: `incomplete`' -Context "Calibration flow run B markdown calibration-pack"
    Assert-TextIncludes -Text $markdownBResult.StdOut -Expected "## Readiness Checks" -Context "Calibration flow run B markdown calibration-pack"
    Assert-TextIncludes -Text $markdownBResult.StdOut -Expected "## Reasons" -Context "Calibration flow run B markdown calibration-pack"

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase13-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }

    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase13-calibration-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreate.ExitCode -eq 0) {
        throw "Denied flow expected create-run to exit non-zero"
    }
    Assert-NoTraceback -Text $deniedCreate.StdErr -Context "Denied flow create-run"

    $deniedCalibrationResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase13-calibration-denied-001"
    )
    Assert-NoTraceback -Text $deniedCalibrationResult.StdErr -Context "Denied flow calibration-pack"
    if ($deniedCalibrationResult.ExitCode -eq 0) {
        throw "Denied flow expected calibration-pack to exit non-zero"
    }
    if (-not $deniedCalibrationResult.StdOut) {
        throw "Denied flow calibration-pack returned empty stdout"
    }
    $deniedCalibration = $deniedCalibrationResult.StdOut | ConvertFrom-Json
    if ([string]$deniedCalibration.status -ne "fail") {
        throw "Denied flow expected status=fail, got $($deniedCalibration.status)"
    }
    if ([string]$deniedCalibration.legal_gate.decision -ne "fail") {
        throw "Denied flow expected legal_gate.decision=fail, got $($deniedCalibration.legal_gate.decision)"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($deniedCalibration.reasons) -ExpectedSubstring "Legal gate failed" -Context "Denied flow calibration-pack"

    foreach ($flowRoot in @($calibrationFlowRoot, $deniedFlowRoot)) {
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

Write-Host "Phase 13 calibration release verification passed."
