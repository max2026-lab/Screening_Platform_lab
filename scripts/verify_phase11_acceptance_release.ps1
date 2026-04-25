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

function Assert-ReasonsInclude {
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

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase11-acceptance-release-verify-" + [guid]::NewGuid().ToString())
$acceptanceFlowRoot = Join-Path $baseTempRoot "acceptance"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $acceptanceFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    Set-Location $acceptanceFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $acceptanceFlowRoot "phase11-acceptance.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Acceptance flow init-db failed.`n$($initResult.StdErr)"
    }

    foreach ($runId in @("phase11-acceptance-a-001", "phase11-acceptance-b-001")) {
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
            throw "Acceptance flow expected create-run run_id=$runId, got $($createRun.run_id)"
        }
        if ([string]$createRun.legal_gate.decision -ne "pass") {
            throw "Acceptance flow expected legal_gate.decision=pass for $runId, got $($createRun.legal_gate.decision)"
        }
    }

    $executeRunA = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase11-acceptance-a-001")
    $executeRunB = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase11-acceptance-b-001")
    if (-not [string]$executeRunA.top_candidate_id) {
        throw "Acceptance flow run A did not return top_candidate_id"
    }
    if (-not [string]$executeRunB.top_candidate_id) {
        throw "Acceptance flow run B did not return top_candidate_id"
    }

    $reviewQueueA = Invoke-LawfulJson -Arguments @(
        "review-queue",
        "--run-id", "phase11-acceptance-a-001",
        "--limit", "5"
    )
    if (@($reviewQueueA).Count -lt 5) {
        throw "Acceptance flow expected at least 5 review candidates for run A"
    }
    foreach ($candidate in @($reviewQueueA | Select-Object -First 5)) {
        $decision = Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase11-acceptance-a-001",
            "--reviewer-id", "phase11-release-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase11 acceptance smoke"
        )
        if ([string]$decision.candidate.current_state -ne "approved_for_archive_quote") {
            throw "Acceptance flow expected candidate $($candidate.candidate_id) to be approved_for_archive_quote"
        }
    }

    $exportCreateA = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase11-acceptance-a-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    if (-not [string]$exportCreateA.audit_manifest.audit_manifest_hash) {
        throw "Acceptance flow expected export audit manifest hash for run A"
    }

    $acceptanceAResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "acceptance-check",
        "--run-id", "phase11-acceptance-a-001",
        "--aoi-area-km2", "100",
        "--comparison-run-id", "phase11-acceptance-b-001"
    )
    Assert-NoTraceback -Text $acceptanceAResult.StdErr -Context "Acceptance flow run A acceptance-check"
    if (-not $acceptanceAResult.StdOut) {
        throw "Acceptance flow run A acceptance-check returned empty stdout"
    }
    $acceptanceA = $acceptanceAResult.StdOut | ConvertFrom-Json
    Assert-JsonFieldsPresent -Object $acceptanceA -Fields @(
        "run_id",
        "status",
        "reasons",
        "checks",
        "kpis",
        "legal_gate",
        "composite_quality",
        "source_scene_manifest_hash",
        "processing_baseline_id",
        "score_formula_version",
        "candidate_count",
        "review_state_counts",
        "export_audit_ready",
        "latest_export_audit_manifest_hash",
        "reproducibility_summary"
    ) -Context "Acceptance flow run A acceptance-check"
    if ([string]$acceptanceA.run_id -ne "phase11-acceptance-a-001") {
        throw "Acceptance flow expected acceptance run_id=phase11-acceptance-a-001, got $($acceptanceA.run_id)"
    }
    if ([string]$acceptanceA.legal_gate.decision -ne "pass") {
        throw "Acceptance flow expected legal_gate.decision=pass, got $($acceptanceA.legal_gate.decision)"
    }
    if (-not [string]$acceptanceA.processing_baseline_id) {
        throw "Acceptance flow expected processing_baseline_id to be present"
    }
    if (-not [string]$acceptanceA.score_formula_version) {
        throw "Acceptance flow expected score_formula_version to be present"
    }
    if ([int]$acceptanceA.candidate_count -ne [int]$acceptanceA.kpis.candidate_count) {
        throw "Acceptance flow expected candidate_count to equal kpis.candidate_count"
    }
    if ($acceptanceA.export_audit_ready -ne $true) {
        throw "Acceptance flow expected export_audit_ready=true"
    }
    if (-not [string]$acceptanceA.latest_export_audit_manifest_hash) {
        throw "Acceptance flow expected latest_export_audit_manifest_hash to be non-empty"
    }
    if ($null -eq $acceptanceA.reproducibility_summary) {
        throw "Acceptance flow expected reproducibility_summary to be present"
    }
    if ([string]$acceptanceA.reproducibility_summary.status -ne "pass") {
        throw "Acceptance flow expected reproducibility_summary.status=pass, got $($acceptanceA.reproducibility_summary.status)"
    }
    if ([double]$acceptanceA.reproducibility_summary.top10_stability_rate -ne 1.0) {
        throw "Acceptance flow expected top10_stability_rate=1.0, got $($acceptanceA.reproducibility_summary.top10_stability_rate)"
    }
    if ($acceptanceA.reproducibility_summary.same_aoi_hash -ne $true) {
        throw "Acceptance flow expected same_aoi_hash=true"
    }
    if ($acceptanceA.reproducibility_summary.same_date_window -ne $true) {
        throw "Acceptance flow expected same_date_window=true"
    }
    if ($acceptanceA.reproducibility_summary.same_source_scene_manifest_hash -ne $true) {
        throw "Acceptance flow expected same_source_scene_manifest_hash=true"
    }
    Assert-CheckNamesPresent -Checks @($acceptanceA.checks) -RequiredNames @(
        "legal_gate",
        "candidate_count",
        "composite_cloud_policy",
        "export_audit_ready",
        "reproducibility"
    ) -Context "Acceptance flow run A acceptance-check"

    $acceptanceBResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "acceptance-check",
        "--run-id", "phase11-acceptance-b-001",
        "--aoi-area-km2", "100"
    )
    Assert-NoTraceback -Text $acceptanceBResult.StdErr -Context "Acceptance flow run B acceptance-check"
    if (-not $acceptanceBResult.StdOut) {
        throw "Acceptance flow run B acceptance-check returned empty stdout"
    }
    $acceptanceB = $acceptanceBResult.StdOut | ConvertFrom-Json
    if ($acceptanceB.export_audit_ready -ne $false) {
        throw "Acceptance flow expected run B export_audit_ready=false"
    }
    Assert-ReasonsInclude -Reasons @($acceptanceB.reasons) -Expected "Export audit manifest not created yet" -Context "Acceptance flow run B acceptance-check"
    if ([string]$acceptanceB.status -eq "pass") {
        throw "Acceptance flow expected run B status to be warn or fail, got pass"
    }
    if ([string]$acceptanceB.status -notin @("warn", "fail")) {
        throw "Acceptance flow expected run B status to be warn or fail, got $($acceptanceB.status)"
    }

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase11-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }

    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase11-acceptance-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($deniedCreate.ExitCode -eq 0) {
        throw "Denied flow expected create-run to exit non-zero"
    }
    Assert-NoTraceback -Text $deniedCreate.StdErr -Context "Denied flow create-run"

    $deniedAcceptanceResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "acceptance-check",
        "--run-id", "phase11-acceptance-denied-001",
        "--aoi-area-km2", "100"
    )
    Assert-NoTraceback -Text $deniedAcceptanceResult.StdErr -Context "Denied flow acceptance-check"
    if (-not $deniedAcceptanceResult.StdOut) {
        throw "Denied flow acceptance-check returned empty stdout"
    }
    $deniedAcceptance = $deniedAcceptanceResult.StdOut | ConvertFrom-Json
    if ([string]$deniedAcceptance.status -ne "fail") {
        throw "Denied flow expected status=fail, got $($deniedAcceptance.status)"
    }
    if ([string]$deniedAcceptance.legal_gate.decision -ne "fail") {
        throw "Denied flow expected legal_gate.decision=fail, got $($deniedAcceptance.legal_gate.decision)"
    }
    Assert-ReasonsInclude -Reasons @($deniedAcceptance.reasons) -Expected "No candidates produced for run" -Context "Denied flow acceptance-check"
    if (-not (@($deniedAcceptance.reasons | ForEach-Object { [string]$_ }) | Where-Object { $_ -like "Legal gate failed*" })) {
        throw "Denied flow expected reasons to include 'Legal gate failed'"
    }

    foreach ($flowRoot in @($acceptanceFlowRoot, $deniedFlowRoot)) {
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

Write-Host "Phase 11 acceptance release verification passed."
