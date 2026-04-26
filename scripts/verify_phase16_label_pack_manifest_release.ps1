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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase16-label-pack-manifest-release-verify-" + [guid]::NewGuid().ToString())
$manifestFlowRoot = Join-Path $baseTempRoot "manifest"
$noReviewFlowRoot = Join-Path $baseTempRoot "no-review"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $manifestFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $noReviewFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"
$originalLocation = Get-Location
try {
    Set-Location $manifestFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $manifestFlowRoot "phase16-label-manifest.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Manifest flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase16-label-manifest-a-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$createRun.run_id -ne "phase16-label-manifest-a-001") {
        throw "Manifest flow expected run_id=phase16-label-manifest-a-001, got $($createRun.run_id)"
    }
    if ([string]$createRun.legal_gate.decision -ne "pass") {
        throw "Manifest flow expected legal_gate.decision=pass, got $($createRun.legal_gate.decision)"
    }

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase16-label-manifest-a-001")
    $candidateCount = [int]$executeRun.candidate_count
    if ($candidateCount -le 0) {
        throw "Manifest flow expected candidate_count > 0"
    }
    if ($candidateCount -lt 2) {
        throw "Manifest flow expected at least 2 candidates so both approve_for_archive_quote and watch decisions can be exercised"
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
        "--run-id", "phase16-label-manifest-a-001",
        "--limit", ([string]$requiredReviewCount)
    )
    $reviewCandidates = @($reviewQueue)
    if ($reviewCandidates.Count -lt $requiredReviewCount) {
        throw "Manifest flow expected at least $requiredReviewCount review candidates"
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
            "--run-id", "phase16-label-manifest-a-001",
            "--reviewer-id", "phase16-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase16 manifest smoke approve"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Manifest flow expected candidate $($candidate.candidate_id) to be approved_for_archive_quote"
        }
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase16-label-manifest-a-001",
            "--reviewer-id", "phase16-release-verifier",
            "--decision", "watch",
            "--note", "phase16 manifest smoke watch"
        )
        if ([string]$decision.candidate.current_state -ne "watch") {
            throw "Manifest flow expected candidate $($candidate.candidate_id) to move to watch"
        }
    }

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase16-label-manifest-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportAuditHash = [string]$exportCreate.audit_manifest.audit_manifest_hash
    if (-not $exportAuditHash) {
        throw "Manifest flow expected export audit manifest hash"
    }

    $packResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-pack",
        "--run-id", "phase16-label-manifest-a-001"
    )
    Assert-NoTraceback -Text $packResult.StdErr -Context "Manifest flow default calibration-label-pack"
    if ($packResult.ExitCode -ne 0) {
        throw "Manifest flow default calibration-label-pack failed.`n$($packResult.StdErr)"
    }
    if (-not $packResult.StdOut) {
        throw "Manifest flow default calibration-label-pack returned empty stdout"
    }
    $pack = $packResult.StdOut | ConvertFrom-Json

    $manifestResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-a-001"
    )
    Assert-NoTraceback -Text $manifestResult.StdErr -Context "Manifest flow default calibration-label-manifest"
    if ($manifestResult.ExitCode -ne 0) {
        throw "Manifest flow default calibration-label-manifest failed.`n$($manifestResult.StdErr)"
    }
    if (-not $manifestResult.StdOut) {
        throw "Manifest flow default calibration-label-manifest returned empty stdout"
    }
    $manifest = $manifestResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $manifest -Fields @(
        "run_id",
        "status",
        "reasons",
        "manifest_type",
        "manifest_version",
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
        "include_pending",
        "label_count",
        "label_pack_hash",
        "label_manifest_hash",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "label_ids"
    ) -Context "Manifest flow default calibration-label-manifest"
    if ([string]$manifest.run_id -ne "phase16-label-manifest-a-001") {
        throw "Manifest flow expected run_id=phase16-label-manifest-a-001, got $($manifest.run_id)"
    }
    if ([string]$manifest.status -ne "ready") {
        throw "Manifest flow expected status=ready, got $($manifest.status)"
    }
    if ([string]$manifest.manifest_type -ne "calibration_label_pack_manifest") {
        throw "Manifest flow expected manifest_type=calibration_label_pack_manifest, got $($manifest.manifest_type)"
    }
    if ([int]$manifest.manifest_version -ne 1) {
        throw "Manifest flow expected manifest_version=1, got $($manifest.manifest_version)"
    }
    if ([string]$manifest.legal_gate.decision -ne "pass") {
        throw "Manifest flow expected legal_gate.decision=pass, got $($manifest.legal_gate.decision)"
    }
    if ([string]$manifest.calibration_policy_id -ne "calibration_policy_v1_0_default") {
        throw "Manifest flow expected calibration_policy_id=calibration_policy_v1_0_default, got $($manifest.calibration_policy_id)"
    }
    if ($manifest.include_pending -ne $false) {
        throw "Manifest flow expected include_pending=false"
    }
    if ([int]$manifest.candidate_count -le 0) {
        throw "Manifest flow expected candidate_count > 0"
    }
    if ([int]$manifest.reviewed_candidate_count -le 0) {
        throw "Manifest flow expected reviewed_candidate_count > 0"
    }
    if ([int]$manifest.approved_candidate_count -le 0) {
        throw "Manifest flow expected approved_candidate_count > 0"
    }
    if ([int]$manifest.watched_candidate_count -le 0) {
        throw "Manifest flow expected watched_candidate_count > 0"
    }
    if (-not $manifest.review_state_counts.PSObject.Properties["approved_for_archive_quote"]) {
        throw "Manifest flow expected review_state_counts to include approved_for_archive_quote"
    }
    if (-not $manifest.review_state_counts.PSObject.Properties["watch"]) {
        throw "Manifest flow expected review_state_counts to include watch"
    }
    if ([double]$manifest.review_coverage_rate -lt 0.20) {
        throw "Manifest flow expected review_coverage_rate >= 0.20, got $($manifest.review_coverage_rate)"
    }
    if ([double]$manifest.top20_review_coverage_rate -lt 0.50) {
        throw "Manifest flow expected top20_review_coverage_rate >= 0.50, got $($manifest.top20_review_coverage_rate)"
    }
    if ($manifest.export_audit_ready -ne $true) {
        throw "Manifest flow expected export_audit_ready=true"
    }
    if (-not [string]$manifest.latest_export_audit_manifest_hash) {
        throw "Manifest flow expected latest_export_audit_manifest_hash to be non-empty"
    }
    if (-not [string]$manifest.label_pack_hash) {
        throw "Manifest flow expected label_pack_hash to be non-empty"
    }
    if (-not [string]$manifest.label_manifest_hash) {
        throw "Manifest flow expected label_manifest_hash to be non-empty"
    }
    $defaultLabelIds = @($manifest.label_ids | ForEach-Object { [string]$_ })
    if ($defaultLabelIds.Count -le 0) {
        throw "Manifest flow expected label_ids to be non-empty"
    }
    if ([int]$manifest.label_count -ne $defaultLabelIds.Count) {
        throw "Manifest flow expected label_count to equal label_ids count"
    }
    if ([string]$manifest.label_pack_hash -ne [string]$pack.label_pack_hash) {
        throw "Manifest flow expected calibration-label-manifest label_pack_hash to equal calibration-label-pack label_pack_hash"
    }

    $manifestRepeatResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-a-001"
    )
    Assert-NoTraceback -Text $manifestRepeatResult.StdErr -Context "Manifest flow repeated calibration-label-manifest"
    if ($manifestRepeatResult.ExitCode -ne 0) {
        throw "Manifest flow repeated calibration-label-manifest failed.`n$($manifestRepeatResult.StdErr)"
    }
    $manifestRepeat = $manifestRepeatResult.StdOut | ConvertFrom-Json
    if ([string]$manifestRepeat.label_manifest_hash -ne [string]$manifest.label_manifest_hash) {
        throw "Manifest flow expected repeated label_manifest_hash to be identical"
    }
    if ([string]$manifestRepeat.label_pack_hash -ne [string]$manifest.label_pack_hash) {
        throw "Manifest flow expected repeated label_pack_hash to be identical"
    }
    if (@($manifestRepeat.label_ids).Count -ne $defaultLabelIds.Count) {
        throw "Manifest flow expected repeated label_ids count to match default label_ids count"
    }

    $manifestPendingResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-a-001",
        "--include-pending"
    )
    Assert-NoTraceback -Text $manifestPendingResult.StdErr -Context "Manifest flow include-pending calibration-label-manifest"
    if ($manifestPendingResult.ExitCode -ne 0) {
        throw "Manifest flow include-pending calibration-label-manifest failed.`n$($manifestPendingResult.StdErr)"
    }
    $manifestPending = $manifestPendingResult.StdOut | ConvertFrom-Json
    if ($manifestPending.include_pending -ne $true) {
        throw "Manifest flow expected include_pending=true for include-pending output"
    }
    if ([int]$manifestPending.label_count -lt [int]$manifest.label_count) {
        throw "Manifest flow expected include-pending label_count >= default label_count"
    }
    if ([int]$manifestPending.pending_candidate_count -gt 0 -and [string]$manifestPending.label_manifest_hash -eq [string]$manifest.label_manifest_hash) {
        throw "Manifest flow expected include-pending label_manifest_hash to differ when pending_candidate_count > 0"
    }
    $defaultCountsJson = ($manifest.review_state_counts | ConvertTo-Json -Compress)
    $pendingCountsJson = ($manifestPending.review_state_counts | ConvertTo-Json -Compress)
    if ($defaultCountsJson -ne $pendingCountsJson) {
        throw "Manifest flow expected include-pending review_state_counts to match default output"
    }

    Set-Location $noReviewFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $noReviewFlowRoot "phase16-no-review.sqlite3"

    $noReviewInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($noReviewInit.ExitCode -ne 0) {
        throw "No-review flow init-db failed.`n$($noReviewInit.StdErr)"
    }
    $noReviewCreate = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase16-label-manifest-no-review-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$noReviewCreate.legal_gate.decision -ne "pass") {
        throw "No-review flow expected legal_gate.decision=pass"
    }
    $noReviewExecute = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase16-label-manifest-no-review-001")
    if ([int]$noReviewExecute.candidate_count -le 0) {
        throw "No-review flow expected candidate_count > 0"
    }

    $noReviewManifestResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-no-review-001"
    )
    Assert-NoTraceback -Text $noReviewManifestResult.StdErr -Context "No-review flow calibration-label-manifest"
    if ($noReviewManifestResult.ExitCode -ne 0) {
        throw "No-review flow calibration-label-manifest unexpectedly failed.`n$($noReviewManifestResult.StdErr)"
    }
    $noReviewManifest = $noReviewManifestResult.StdOut | ConvertFrom-Json
    if ([string]$noReviewManifest.status -ne "incomplete") {
        throw "No-review flow expected status=incomplete, got $($noReviewManifest.status)"
    }
    Assert-ReasonsIncludeExact -Reasons @($noReviewManifest.reasons) -Expected "No reviewed candidates available for calibration label pack" -Context "No-review flow calibration-label-manifest"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewManifest.reasons) -ExpectedSubstring "Review coverage rate" -Context "No-review flow calibration-label-manifest"
    Assert-ReasonsIncludeSubstring -Reasons @($noReviewManifest.reasons) -ExpectedSubstring "Top-20 review coverage rate" -Context "No-review flow calibration-label-manifest"
    Assert-ReasonsIncludeExact -Reasons @($noReviewManifest.reasons) -Expected "Export audit manifest not created yet" -Context "No-review flow calibration-label-manifest"
    if ([int]$noReviewManifest.label_count -ne 0) {
        throw "No-review flow expected label_count=0"
    }

    $noReviewMarkdownResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-no-review-001",
        "--output", "markdown"
    )
    Assert-NoTraceback -Text $noReviewMarkdownResult.StdErr -Context "No-review flow markdown calibration-label-manifest"
    if ($noReviewMarkdownResult.ExitCode -ne 0) {
        throw "No-review flow markdown calibration-label-manifest unexpectedly failed.`n$($noReviewMarkdownResult.StdErr)"
    }
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "# Calibration Label Manifest" -Context "No-review flow markdown calibration-label-manifest"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected 'Status: `incomplete`' -Context "No-review flow markdown calibration-label-manifest"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "Label pack hash:" -Context "No-review flow markdown calibration-label-manifest"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "Label manifest hash:" -Context "No-review flow markdown calibration-label-manifest"
    Assert-TextIncludes -Text $noReviewMarkdownResult.StdOut -Expected "## Reasons" -Context "No-review flow markdown calibration-label-manifest"

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase16-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }
    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase16-label-manifest-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreate.ExitCode -eq 0) {
        throw "Denied flow expected create-run to exit non-zero"
    }
    Assert-NoTraceback -Text $deniedCreate.StdErr -Context "Denied flow create-run"

    $deniedManifestResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-manifest",
        "--run-id", "phase16-label-manifest-denied-001"
    )
    Assert-NoTraceback -Text $deniedManifestResult.StdErr -Context "Denied flow calibration-label-manifest"
    if ($deniedManifestResult.ExitCode -eq 0) {
        throw "Denied flow expected calibration-label-manifest to exit non-zero"
    }
    if (-not $deniedManifestResult.StdOut) {
        throw "Denied flow calibration-label-manifest returned empty stdout"
    }
    $deniedManifest = $deniedManifestResult.StdOut | ConvertFrom-Json
    if ([string]$deniedManifest.status -ne "fail") {
        throw "Denied flow expected status=fail, got $($deniedManifest.status)"
    }
    if ([string]$deniedManifest.legal_gate.decision -ne "fail") {
        throw "Denied flow expected legal_gate.decision=fail, got $($deniedManifest.legal_gate.decision)"
    }
    Assert-ReasonsIncludeSubstring -Reasons @($deniedManifest.reasons) -ExpectedSubstring "Legal gate failed" -Context "Denied flow calibration-label-manifest"

    foreach ($flowRoot in @($manifestFlowRoot, $noReviewFlowRoot, $deniedFlowRoot)) {
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

Write-Host "Phase 16 label pack manifest release verification passed."
