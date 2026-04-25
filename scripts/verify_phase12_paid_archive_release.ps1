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

function Assert-StderrIncludes {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Text,

        [Parameter(Mandatory = $true)]
        [string] $Expected,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if ($Text -notlike "*$Expected*") {
        throw "$Context expected stderr to include '$Expected', got: $Text"
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

$baseTempRoot = Join-Path $env:TEMP ("phase12-paid-archive-release-verify-" + [guid]::NewGuid().ToString())
$paidFlowRoot = Join-Path $baseTempRoot "paid"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
New-Item -ItemType Directory -Path $paidFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    Set-Location $paidFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $paidFlowRoot "phase12-paid.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Paid flow init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase12-paid-archive-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ([string]$createRun.run_id -ne "phase12-paid-archive-001") {
        throw "Paid flow expected create-run run_id=phase12-paid-archive-001, got $($createRun.run_id)"
    }
    if ([string]$createRun.legal_gate.decision -ne "pass") {
        throw "Paid flow expected legal_gate.decision=pass, got $($createRun.legal_gate.decision)"
    }

    $executeRun = Invoke-LawfulJson -Arguments @(
        "execute-run",
        "--run-id", "phase12-paid-archive-001"
    )
    $topCandidateId = [string]$executeRun.top_candidate_id
    if (-not $topCandidateId) {
        throw "Paid flow execute-run did not return top_candidate_id"
    }

    $quoteBeforeApproval = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "paid-quote-create",
        "--candidate-id", $topCandidateId,
        "--provider-quote-id", "phase12-quote-001",
        "--amount", "175.0",
        "--credits", "95.0",
        "--currency", "usd",
        "--eula-reference", "phase12-eula-001",
        "--project-id", "phase12-project-001"
    )
    if ($quoteBeforeApproval.ExitCode -eq 0) {
        throw "Paid flow expected paid-quote-create before review approval to fail"
    }
    Assert-StderrIncludes -Text $quoteBeforeApproval.StdErr -Expected "candidate review state must be approved_for_archive_quote" -Context "Paid flow quote before approval"
    Assert-NoTraceback -Text $quoteBeforeApproval.StdErr -Context "Paid flow quote before approval"

    $reviewDecision = Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", $topCandidateId,
        "--run-id", "phase12-paid-archive-001",
        "--reviewer-id", "phase12-release-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase12 paid archive smoke"
    )
    if ([string]$reviewDecision.candidate.current_state -ne "approved_for_archive_quote") {
        throw "Paid flow expected top candidate to move to approved_for_archive_quote"
    }

    $quoteCreate = Invoke-LawfulJson -Arguments @(
        "paid-quote-create",
        "--candidate-id", $topCandidateId,
        "--provider-quote-id", "phase12-quote-001",
        "--amount", "175.0",
        "--credits", "95.0",
        "--currency", "usd",
        "--eula-reference", "phase12-eula-001",
        "--project-id", "phase12-project-001"
    )
    Assert-JsonFieldsPresent -Object $quoteCreate -Fields @(
        "candidate_id",
        "run_id",
        "current_review_state",
        "legal_gate",
        "quote_id",
        "provider_quote_id",
        "amount",
        "credits",
        "currency",
        "eula_reference",
        "project_id",
        "paid_escalation_ready",
        "reasons"
    ) -Context "Paid flow quote create"
    if ([string]$quoteCreate.candidate_id -ne $topCandidateId) {
        throw "Paid flow expected quote candidate_id to equal top candidate"
    }
    if ([string]$quoteCreate.run_id -ne "phase12-paid-archive-001") {
        throw "Paid flow expected quote run_id=phase12-paid-archive-001, got $($quoteCreate.run_id)"
    }
    if ([string]$quoteCreate.current_review_state -ne "approved_for_archive_quote") {
        throw "Paid flow expected current_review_state=approved_for_archive_quote, got $($quoteCreate.current_review_state)"
    }
    if ([string]$quoteCreate.legal_gate.decision -ne "pass") {
        throw "Paid flow expected quote legal_gate.decision=pass, got $($quoteCreate.legal_gate.decision)"
    }
    if ([string]$quoteCreate.provider_quote_id -ne "phase12-quote-001") {
        throw "Paid flow expected provider_quote_id=phase12-quote-001, got $($quoteCreate.provider_quote_id)"
    }
    if ([string]$quoteCreate.quote_id -ne "phase12-quote-001") {
        throw "Paid flow expected quote_id=phase12-quote-001, got $($quoteCreate.quote_id)"
    }
    if ([string]$quoteCreate.project_id -ne "phase12-project-001") {
        throw "Paid flow expected project_id=phase12-project-001, got $($quoteCreate.project_id)"
    }
    if ($quoteCreate.paid_escalation_ready -ne $true) {
        throw "Paid flow expected paid_escalation_ready=true"
    }
    Assert-ReasonsInclude -Reasons @($quoteCreate.reasons) -Expected "Paid archive escalation checks passed" -Context "Paid flow quote create"

    $orderBeforeExport = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "paid-order-create",
        "--candidate-id", $topCandidateId,
        "--provider-quote-id", "phase12-quote-001",
        "--provider-order-id", "phase12-order-001",
        "--requested-by", "phase12-release-verifier"
    )
    if ($orderBeforeExport.ExitCode -eq 0) {
        throw "Paid flow expected paid-order-create before export audit to fail"
    }
    Assert-StderrIncludes -Text $orderBeforeExport.StdErr -Expected "export audit manifest must exist before paid order creation" -Context "Paid flow order before export"
    Assert-NoTraceback -Text $orderBeforeExport.StdErr -Context "Paid flow order before export"

    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase12-paid-archive-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $exportAuditHash = [string]$exportCreate.audit_manifest.audit_manifest_hash
    if (-not $exportAuditHash) {
        throw "Paid flow expected export audit manifest hash to be non-empty"
    }

    $orderCreate = Invoke-LawfulJson -Arguments @(
        "paid-order-create",
        "--candidate-id", $topCandidateId,
        "--provider-quote-id", "phase12-quote-001",
        "--provider-order-id", "phase12-order-001",
        "--requested-by", "phase12-release-verifier"
    )
    Assert-JsonFieldsPresent -Object $orderCreate -Fields @(
        "candidate_id",
        "run_id",
        "provider_quote_id",
        "provider_order_id",
        "paid_status",
        "requested_by",
        "latest_export_audit_manifest_hash",
        "legal_gate",
        "reasons"
    ) -Context "Paid flow order create"
    if ([string]$orderCreate.provider_quote_id -ne "phase12-quote-001") {
        throw "Paid flow expected order provider_quote_id=phase12-quote-001, got $($orderCreate.provider_quote_id)"
    }
    if ([string]$orderCreate.provider_order_id -ne "phase12-order-001") {
        throw "Paid flow expected order provider_order_id=phase12-order-001, got $($orderCreate.provider_order_id)"
    }
    if ([string]$orderCreate.paid_status -ne "order_submitted") {
        throw "Paid flow expected order paid_status=order_submitted, got $($orderCreate.paid_status)"
    }
    if ([string]$orderCreate.requested_by -ne "phase12-release-verifier") {
        throw "Paid flow expected requested_by=phase12-release-verifier, got $($orderCreate.requested_by)"
    }
    if ([string]$orderCreate.latest_export_audit_manifest_hash -ne $exportAuditHash) {
        throw "Paid flow expected latest_export_audit_manifest_hash to equal export audit manifest hash"
    }
    if ([string]$orderCreate.legal_gate.decision -ne "pass") {
        throw "Paid flow expected order legal_gate.decision=pass, got $($orderCreate.legal_gate.decision)"
    }
    Assert-ReasonsInclude -Reasons @($orderCreate.reasons) -Expected "Paid archive order checks passed" -Context "Paid flow order create"

    $orderStatus = Invoke-LawfulJson -Arguments @(
        "paid-order-status",
        "--provider-order-id", "phase12-order-001",
        "--paid-status", "order_confirmed"
    )
    Assert-JsonFieldsPresent -Object $orderStatus -Fields @(
        "candidate_id",
        "run_id",
        "provider_quote_id",
        "provider_order_id",
        "paid_status",
        "requested_by",
        "latest_export_audit_manifest_hash",
        "legal_gate",
        "reasons"
    ) -Context "Paid flow order status"
    if ([string]$orderStatus.paid_status -ne "order_confirmed") {
        throw "Paid flow expected order status update to return paid_status=order_confirmed, got $($orderStatus.paid_status)"
    }
    if ([string]$orderStatus.latest_export_audit_manifest_hash -ne $exportAuditHash) {
        throw "Paid flow expected order status output latest_export_audit_manifest_hash to equal export audit manifest hash"
    }
    if ([string]$orderStatus.requested_by -ne "phase12-release-verifier") {
        throw "Paid flow expected order status requested_by=phase12-release-verifier, got $($orderStatus.requested_by)"
    }

    $missingOrderStatus = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "paid-order-status",
        "--provider-order-id", "phase12-missing-order-001",
        "--paid-status", "order_confirmed"
    )
    if ($missingOrderStatus.ExitCode -eq 0) {
        throw "Paid flow expected missing order status update to fail"
    }
    Assert-StderrIncludes -Text $missingOrderStatus.StdErr -Expected "paid order not found" -Context "Paid flow missing order status"
    Assert-NoTraceback -Text $missingOrderStatus.StdErr -Context "Paid flow missing order status"

    Set-Location $deniedFlowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase12-denied.sqlite3"

    $deniedInit = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($deniedInit.ExitCode -ne 0) {
        throw "Denied flow init-db failed.`n$($deniedInit.StdErr)"
    }

    $deniedCreate = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase12-paid-denied-001",
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
        "--run-id", "phase12-paid-denied-001",
        "--aoi-area-km2", "100"
    )
    Assert-NoTraceback -Text $deniedAcceptanceResult.StdErr -Context "Denied flow acceptance-check"
    if (-not $deniedAcceptanceResult.StdOut) {
        throw "Denied flow acceptance-check returned empty stdout"
    }
    $deniedAcceptance = $deniedAcceptanceResult.StdOut | ConvertFrom-Json
    if ([string]$deniedAcceptance.status -ne "fail") {
        throw "Denied flow expected acceptance status=fail, got $($deniedAcceptance.status)"
    }
    if ([string]$deniedAcceptance.legal_gate.decision -ne "fail") {
        throw "Denied flow expected legal_gate.decision=fail, got $($deniedAcceptance.legal_gate.decision)"
    }

    foreach ($flowRoot in @($paidFlowRoot, $deniedFlowRoot)) {
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

Write-Host "Phase 12 paid archive release verification passed."
