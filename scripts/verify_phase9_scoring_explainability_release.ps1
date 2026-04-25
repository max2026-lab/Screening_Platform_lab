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

function Assert-ScoringExplanationShape {
    param(
        [Parameter(Mandatory = $true)]
        [object] $ScoringExplanation,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    if ($null -eq $ScoringExplanation) {
        throw "$Context missing scoring_explanation"
    }

    foreach ($field in @(
        "candidate_score",
        "parent_tile_score",
        "score_formula_version",
        "rank",
        "parent_tile_rank",
        "component_scores",
        "penalties",
        "source_scene_count",
        "source_scene_ids",
        "composite_quality",
        "boundary_touching",
        "area_m2",
        "reason"
    )) {
        if (-not $ScoringExplanation.PSObject.Properties[$field]) {
            throw "$Context scoring_explanation missing field '$field'"
        }
    }
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase9-scoring-explainability-release-verify-" + [guid]::NewGuid().ToString())
$flowRoot = Join-Path $baseTempRoot "phase9-flow"
New-Item -ItemType Directory -Path $flowRoot -Force | Out-Null

$sampleAoiPath = Join-Path $repoRoot "tests\fixtures\sample_aoi.geojson"

$originalLocation = Get-Location
try {
    Set-Location $flowRoot
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_ENDPOINTS_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:LAWFUL_ANOMALY_PREPROCESSING_CONFIG_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $flowRoot "phase9-explainability.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Flow A init-db failed.`n$($initResult.StdErr)"
    }

    $createRun = Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase9-explainability-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    if ($createRun.legal_gate.decision -ne "pass") {
        throw "Flow A create-run expected legal_gate.decision=pass, got $($createRun.legal_gate.decision)"
    }

    $executeRun = Invoke-LawfulJson -Arguments @(
        "execute-run",
        "--run-id", "phase9-explainability-001"
    )
    $topCandidateId = [string]$executeRun.top_candidate_id
    if (-not $topCandidateId) {
        throw "Flow A execute-run did not return top_candidate_id"
    }

    $reviewShow = Invoke-LawfulJson -Arguments @(
        "review-show",
        "--candidate-id", $topCandidateId
    )
    $exportCreate = Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase9-explainability-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    )
    $reviewShowRepeat = Invoke-LawfulJson -Arguments @(
        "review-show",
        "--candidate-id", $topCandidateId
    )

    $reviewCandidate = $reviewShow.candidate
    Assert-ScoringExplanationShape -ScoringExplanation $reviewCandidate.scoring_explanation -Context "Flow A review-show"

    if ($reviewCandidate.scoring_explanation.candidate_score -ne $reviewCandidate.candidate_score) {
        throw "Flow A expected scoring_explanation.candidate_score to equal candidate.candidate_score"
    }
    if ($reviewCandidate.scoring_explanation.parent_tile_score -ne $reviewCandidate.parent_tile_score) {
        throw "Flow A expected scoring_explanation.parent_tile_score to equal candidate.parent_tile_score"
    }
    if ([int]$reviewCandidate.scoring_explanation.rank -ne 1) {
        throw "Flow A expected scoring_explanation.rank=1 for top candidate, got $($reviewCandidate.scoring_explanation.rank)"
    }

    $reviewSourceSceneIdsJson = $reviewCandidate.scoring_explanation.source_scene_ids | ConvertTo-Json -Depth 10 -Compress
    $candidateSourceSceneIdsJson = $reviewCandidate.source_scene_ids | ConvertTo-Json -Depth 10 -Compress
    if ($reviewSourceSceneIdsJson -ne $candidateSourceSceneIdsJson) {
        throw "Flow A expected scoring_explanation.source_scene_ids to equal candidate.source_scene_ids"
    }
    if ([int]$reviewCandidate.scoring_explanation.source_scene_count -ne @($reviewCandidate.source_scene_ids).Count) {
        throw "Flow A expected scoring_explanation.source_scene_count to match source_scene_ids count"
    }

    $reason = [string]$reviewCandidate.scoring_explanation.reason
    if (-not $reason) {
        throw "Flow A expected scoring_explanation.reason to be non-empty"
    }
    foreach ($fragment in @("candidate score", "source scenes", "boundary touching")) {
        if ($reason -notlike "*$fragment*") {
            throw "Flow A expected scoring_explanation.reason to include '$fragment', got: $reason"
        }
    }

    $exportCandidate = $null
    foreach ($candidate in $exportCreate.candidates) {
        if ([string]$candidate.candidate_id -eq $topCandidateId) {
            $exportCandidate = $candidate
            break
        }
    }
    if ($null -eq $exportCandidate) {
        throw "Flow A export-create did not include top candidate $topCandidateId"
    }
    Assert-ScoringExplanationShape -ScoringExplanation $exportCandidate.scoring_explanation -Context "Flow A export-create"

    $reviewExplanationJson = $reviewCandidate.scoring_explanation | ConvertTo-Json -Depth 20 -Compress
    $exportExplanationJson = $exportCandidate.scoring_explanation | ConvertTo-Json -Depth 20 -Compress
    if ($reviewExplanationJson -ne $exportExplanationJson) {
        throw "Flow A expected export scoring_explanation to equal review-show scoring_explanation"
    }

    if ($exportCreate.precision_tier -ne "restricted") {
        throw "Flow A expected export precision_tier=restricted, got $($exportCreate.precision_tier)"
    }
    if ($exportCreate.exact_coordinates_included -ne $false) {
        throw "Flow A expected restricted export to exclude exact coordinates"
    }

    $repeatExplanationJson = $reviewShowRepeat.candidate.scoring_explanation | ConvertTo-Json -Depth 20 -Compress
    if ($reviewExplanationJson -ne $repeatExplanationJson) {
        throw "Flow A expected repeated review-show scoring_explanation JSON to be identical"
    }

    if (Test-Path (Join-Path $flowRoot "config")) {
        throw "Flow A copied config into outside working directory"
    }
    if (Test-Path (Join-Path $flowRoot "sitecustomize.py")) {
        throw "Flow A created sitecustomize.py in outside working directory"
    }
    if (Test-Path Env:PYTHONPATH) {
        throw "PYTHONPATH must not be set after verification flow"
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

Write-Host "Phase 9 scoring explainability release verification passed."
