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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$expectedBaselinePath = (Resolve-Path (Join-Path $repoRoot "src\lawful_anomaly_screening\config\baselines\baseline_v1_5_default.json")).Path

Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue

$baselineResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("show-baseline")
Assert-NoTraceback -Text $baselineResult.StdErr -Context "Baseline/config show-baseline"
if ($baselineResult.ExitCode -ne 0) {
    throw "Baseline/config show-baseline failed.`n$($baselineResult.StdErr)"
}
if (-not $baselineResult.StdOut) {
    throw "Baseline/config show-baseline returned empty stdout"
}
$baseline = $baselineResult.StdOut | ConvertFrom-Json
if ($null -eq $baseline.calibration_policy) {
    throw "Baseline/config expected calibration_policy to be present"
}
if ([string]$baseline.calibration_policy.calibration_policy_id -ne "calibration_policy_v1_0_default") {
    throw "Baseline/config expected calibration_policy_id=calibration_policy_v1_0_default, got $($baseline.calibration_policy.calibration_policy_id)"
}
if ([double]$baseline.calibration_policy.review_coverage_minimum_rate -ne 0.20) {
    throw "Baseline/config expected review_coverage_minimum_rate=0.20, got $($baseline.calibration_policy.review_coverage_minimum_rate)"
}
if ([double]$baseline.calibration_policy.top20_review_coverage_minimum_rate -ne 0.50) {
    throw "Baseline/config expected top20_review_coverage_minimum_rate=0.50, got $($baseline.calibration_policy.top20_review_coverage_minimum_rate)"
}
if ($baseline.calibration_policy.requires_export_audit_manifest -ne $true) {
    throw "Baseline/config expected requires_export_audit_manifest=true"
}
if ($baseline.calibration_policy.requires_reproducibility_comparison -ne $true) {
    throw "Baseline/config expected requires_reproducibility_comparison=true"
}
if ([int]$baseline.calibration_policy.minimum_candidate_count -ne 1) {
    throw "Baseline/config expected minimum_candidate_count=1, got $($baseline.calibration_policy.minimum_candidate_count)"
}
if ($baseline.calibration_policy.paid_escalation_required -ne $false) {
    throw "Baseline/config expected paid_escalation_required=false"
}

$baseTempRoot = Join-Path $env:TEMP ("phase14-calibration-policy-release-verify-" + [guid]::NewGuid().ToString())
$policyFlowRoot = Join-Path $baseTempRoot "policy"
New-Item -ItemType Directory -Path $policyFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location
try {
    Set-Location $policyFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $policyFlowRoot "phase14-policy.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Policy flow init-db failed.`n$($initResult.StdErr)"
    }

    foreach ($runId in @("phase14-policy-a-001", "phase14-policy-b-001")) {
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
            throw "Policy flow expected create-run run_id=$runId, got $($createRun.run_id)"
        }
        if ([string]$createRun.legal_gate.decision -ne "pass") {
            throw "Policy flow expected legal_gate.decision=pass for $runId, got $($createRun.legal_gate.decision)"
        }
    }

    $executeRunA = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase14-policy-a-001")
    $executeRunB = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase14-policy-b-001")
    $runACandidateCount = [int]$executeRunA.candidate_count
    $runBCandidateCount = [int]$executeRunB.candidate_count
    if ($runACandidateCount -le 0) {
        throw "Policy flow expected run A candidate_count > 0"
    }
    if ($runACandidateCount -lt 2) {
        throw "Policy flow expected at least 2 candidates in run A so both approve_for_archive_quote and watch decisions can be exercised"
    }
    if ($runBCandidateCount -le 0) {
        throw "Policy flow expected run B candidate_count > 0"
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
        "--run-id", "phase14-policy-a-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidatesA = @($reviewQueueA)
    if ($reviewCandidatesA.Count -lt $requiredReviewCount) {
        throw "Policy flow expected at least $requiredReviewCount review candidates for run A"
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
            "--run-id", "phase14-policy-a-001",
            "--reviewer-id", "phase14-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase14 policy smoke approve"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Policy flow expected candidate $($candidate.candidate_id) to be approved_for_archive_quote"
        }
    }

    foreach ($candidate in @($reviewCandidatesA | Select-Object -Skip $approveCount -First $watchCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase14-policy-a-001",
            "--reviewer-id", "phase14-release-verifier",
            "--decision", "watch",
            "--note", "phase14 policy smoke watch"
        )
        if ([string]$decision.candidate.current_state -ne "watch") {
            throw "Policy flow expected candidate $($candidate.candidate_id) to move to watch"
        }
    }

    $exportCreateA = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase14-policy-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportAuditHash = [string]$exportCreateA.audit_manifest.audit_manifest_hash
    if (-not $exportAuditHash) {
        throw "Policy flow expected export audit manifest hash for run A"
    }

    $calibrationAResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase14-policy-a-001",
        "--comparison-run-id", "phase14-policy-b-001"
    )
    Assert-NoTraceback -Text $calibrationAResult.StdErr -Context "Policy flow run A calibration-pack"
    if ($calibrationAResult.ExitCode -ne 0) {
        throw "Policy flow run A calibration-pack failed.`n$($calibrationAResult.StdErr)"
    }
    if (-not $calibrationAResult.StdOut) {
        throw "Policy flow run A calibration-pack returned empty stdout"
    }
    $calibrationA = $calibrationAResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $calibrationA -Fields @(
        "calibration_policy_id",
        "calibration_policy",
        "threshold_policy_source",
        "calibration_readiness_checks"
    ) -Context "Policy flow run A calibration-pack"
    if ([string]$calibrationA.calibration_policy_id -ne "calibration_policy_v1_0_default") {
        throw "Policy flow expected calibration_policy_id=calibration_policy_v1_0_default, got $($calibrationA.calibration_policy_id)"
    }
    if ([double]$calibrationA.calibration_policy.review_coverage_minimum_rate -ne 0.20) {
        throw "Policy flow expected calibration_policy.review_coverage_minimum_rate=0.20"
    }
    if ([double]$calibrationA.calibration_policy.top20_review_coverage_minimum_rate -ne 0.50) {
        throw "Policy flow expected calibration_policy.top20_review_coverage_minimum_rate=0.50"
    }
    if ($calibrationA.calibration_policy.requires_export_audit_manifest -ne $true) {
        throw "Policy flow expected calibration_policy.requires_export_audit_manifest=true"
    }
    if ($calibrationA.calibration_policy.requires_reproducibility_comparison -ne $true) {
        throw "Policy flow expected calibration_policy.requires_reproducibility_comparison=true"
    }
    if ([int]$calibrationA.calibration_policy.minimum_candidate_count -ne 1) {
        throw "Policy flow expected calibration_policy.minimum_candidate_count=1"
    }
    if ($calibrationA.calibration_policy.paid_escalation_required -ne $false) {
        throw "Policy flow expected calibration_policy.paid_escalation_required=false"
    }
    if (-not [string]$calibrationA.threshold_policy_source) {
        throw "Policy flow expected threshold_policy_source to be non-empty"
    }
    if ([string]$calibrationA.threshold_policy_source -ne $expectedBaselinePath) {
        throw "Policy flow expected threshold_policy_source=$expectedBaselinePath, got $($calibrationA.threshold_policy_source)"
    }
    if ([string]$calibrationA.status -ne "ready") {
        throw "Policy flow expected status=ready, got $($calibrationA.status)"
    }

    $checkByName = @{}
    foreach ($check in @($calibrationA.calibration_readiness_checks)) {
        $checkByName[[string]$check.name] = $check
    }
    Assert-CheckNamesPresent -Checks @($calibrationA.calibration_readiness_checks) -RequiredNames @(
        "candidate_count",
        "review_coverage_rate",
        "top20_review_coverage_rate",
        "export_audit_ready",
        "reproducibility"
    ) -Context "Policy flow run A calibration-pack"
    if ([string]$checkByName["candidate_count"].target -ne ">= 1") {
        throw "Policy flow expected candidate_count target='>= 1', got $($checkByName["candidate_count"].target)"
    }
    if ([string]$checkByName["review_coverage_rate"].target -ne ">= 0.20") {
        throw "Policy flow expected review_coverage_rate target='>= 0.20', got $($checkByName["review_coverage_rate"].target)"
    }
    if ([string]$checkByName["top20_review_coverage_rate"].target -ne ">= 0.50") {
        throw "Policy flow expected top20_review_coverage_rate target='>= 0.50', got $($checkByName["top20_review_coverage_rate"].target)"
    }
    if ([string]$checkByName["export_audit_ready"].target -ne "export audit manifest available") {
        throw "Policy flow expected export_audit_ready target='export audit manifest available', got $($checkByName["export_audit_ready"].target)"
    }
    if ([string]$checkByName["reproducibility"].target -ne "comparison run supplied with pass status") {
        throw "Policy flow expected reproducibility target='comparison run supplied with pass status', got $($checkByName["reproducibility"].target)"
    }

    $acceptanceAResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "acceptance-check",
        "--run-id", "phase14-policy-a-001",
        "--aoi-area-km2", "100",
        "--comparison-run-id", "phase14-policy-b-001"
    )
    Assert-NoTraceback -Text $acceptanceAResult.StdErr -Context "Policy flow run A acceptance-check"
    if (-not $acceptanceAResult.StdOut) {
        throw "Policy flow run A acceptance-check returned empty stdout"
    }
    $acceptanceA = $acceptanceAResult.StdOut | ConvertFrom-Json
    if (-not $acceptanceA.PSObject.Properties["calibration_policy_id"]) {
        throw "Policy flow run A acceptance-check missing calibration_policy_id"
    }
    if ([string]$acceptanceA.calibration_policy_id -ne "calibration_policy_v1_0_default") {
        throw "Policy flow expected acceptance-check calibration_policy_id=calibration_policy_v1_0_default, got $($acceptanceA.calibration_policy_id)"
    }

    $calibrationBResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-pack",
        "--run-id", "phase14-policy-b-001"
    )
    Assert-NoTraceback -Text $calibrationBResult.StdErr -Context "Policy flow run B calibration-pack"
    if ($calibrationBResult.ExitCode -ne 0) {
        throw "Policy flow run B calibration-pack unexpectedly failed.`n$($calibrationBResult.StdErr)"
    }
    if (-not $calibrationBResult.StdOut) {
        throw "Policy flow run B calibration-pack returned empty stdout"
    }
    $calibrationB = $calibrationBResult.StdOut | ConvertFrom-Json
    if ([string]$calibrationB.status -ne "incomplete") {
        throw "Policy flow expected run B status=incomplete, got $($calibrationB.status)"
    }
    if ([string]$calibrationB.calibration_policy_id -ne "calibration_policy_v1_0_default") {
        throw "Policy flow expected run B calibration_policy_id=calibration_policy_v1_0_default, got $($calibrationB.calibration_policy_id)"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($calibrationB.reasons) -ExpectedSubstring "Review coverage rate" -Context "Policy flow run B calibration-pack"
    Assert-ReasonsIncludeSubstring -Reasons @($calibrationB.reasons) -ExpectedSubstring "Top-20 review coverage rate" -Context "Policy flow run B calibration-pack"
    Assert-ReasonsIncludeExact -Reasons @($calibrationB.reasons) -Expected "Export audit manifest not created yet" -Context "Policy flow run B calibration-pack"
    Assert-ReasonsIncludeExact -Reasons @($calibrationB.reasons) -Expected "Reproducibility comparison run not supplied" -Context "Policy flow run B calibration-pack"

    foreach ($flowRoot in @($policyFlowRoot)) {
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

Write-Host "Phase 14 calibration policy release verification passed."
