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
        if ($Object -is [System.Collections.IDictionary]) {
            if (-not $Object.Contains($field)) {
                throw "$Context missing field '$field'"
            }
        }
        elseif (-not $Object.PSObject.Properties[$field]) {
            throw "$Context missing field '$field'"
        }
    }
}

function Get-SHA256Hex {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath
    )

    return (Get-FileHash $FilePath -Algorithm SHA256).Hash.ToLower()
}

function Write-LfText {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path,

        [Parameter(Mandatory = $true)]
        [string] $Content
    )

    $normalized = $Content -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $normalized, $utf8NoBom)
}

function Recompute-SHA256SUMS {
    param(
        [Parameter(Mandatory = $true)]
        [string] $EvidenceDir
    )

    $jsonPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.json"
    $mdPath = Join-Path $EvidenceDir "calibration_registry_snapshot_diff.md"
    $jsonHash = Get-SHA256Hex -FilePath $jsonPath
    $mdHash = Get-SHA256Hex -FilePath $mdPath
    $sumsText = "$jsonHash  calibration_registry_snapshot_diff.json`n$mdHash  calibration_registry_snapshot_diff.md`n"
    Write-LfText -Path (Join-Path $EvidenceDir "SHA256SUMS.txt") -Content $sumsText
}

function Read-Utf8Text {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function ConvertTo-Hashtable {
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [object] $InputObject
    )

    if ($null -eq $InputObject) {
        return $null
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $InputObject.Keys) {
            $result[[string]$key] = ConvertTo-Hashtable -InputObject $InputObject[$key]
        }
        return $result
    }

    if (($InputObject -is [System.Collections.IEnumerable]) -and -not ($InputObject -is [string])) {
        $items = @()
        foreach ($item in $InputObject) {
            $items += ,(ConvertTo-Hashtable -InputObject $item)
        }
        return $items
    }

    $properties = @()
    if ($InputObject.PSObject) {
        $properties = @($InputObject.PSObject.Properties)
    }
    if ($properties.Count -gt 0 -and -not ($InputObject -is [string])) {
        $result = @{}
        foreach ($property in $properties) {
            $result[$property.Name] = ConvertTo-Hashtable -InputObject $property.Value
        }
        return $result
    }

    return $InputObject
}

function Assert-SumsContainHash {
    param(
        [Parameter(Mandatory = $true)]
        [string] $SumsText,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedHash,

        [Parameter(Mandatory = $true)]
        [string] $FileName,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $expectedLine = "$ExpectedHash  $FileName"
    if (-not $SumsText.Contains($expectedLine)) {
        throw "$Context expected SHA256SUMS.txt to contain '$expectedLine'"
    }
}

function Assert-SignoffBundle {
    param(
        [Parameter(Mandatory = $true)]
        [string] $OutputDir,

        [Parameter(Mandatory = $true)]
        [hashtable] $StdoutResult,

        [Parameter(Mandatory = $true)]
        [string] $Context
    )

    $jsonPath = Join-Path $OutputDir "calibration_signoff_evidence.json"
    $mdPath = Join-Path $OutputDir "calibration_signoff_evidence.md"
    $sumsPath = Join-Path $OutputDir "SHA256SUMS.txt"

    foreach ($path in @($jsonPath, $mdPath, $sumsPath)) {
        if (-not (Test-Path $path)) {
            throw "$Context missing expected output file: $path"
        }
    }

    $jsonText = Read-Utf8Text -Path $jsonPath
    $mdText = Read-Utf8Text -Path $mdPath
    $sumsText = Read-Utf8Text -Path $sumsPath

    $diskJson = ConvertTo-Hashtable -InputObject (ConvertFrom-Json -InputObject $jsonText)

    foreach ($field in @(
        "status",
        "acceptance_status",
        "decision_hash",
        "signoff_hash",
        "diff_hash",
        "added_count",
        "removed_count",
        "changed_count",
        "unchanged_count"
    )) {
        if ([string]$diskJson[$field] -ne [string]$StdoutResult[$field]) {
            throw "$Context disk JSON field '$field' did not match stdout JSON"
        }
    }

    if (($diskJson.files | ConvertTo-Json -Compress) -ne ($StdoutResult.files | ConvertTo-Json -Compress)) {
        throw "$Context disk JSON files array did not match stdout JSON"
    }
    $diskSourceEvidenceHashes = ConvertTo-Hashtable -InputObject $diskJson.source_evidence_file_hashes
    $stdoutSourceEvidenceHashes = ConvertTo-Hashtable -InputObject $StdoutResult.source_evidence_file_hashes
    $diskSourceEvidenceKeys = @($diskSourceEvidenceHashes.Keys | Sort-Object)
    $stdoutSourceEvidenceKeys = @($stdoutSourceEvidenceHashes.Keys | Sort-Object)
    if (($diskSourceEvidenceKeys | ConvertTo-Json -Compress) -ne ($stdoutSourceEvidenceKeys | ConvertTo-Json -Compress)) {
        throw "$Context disk JSON source_evidence_file_hashes keys did not match stdout JSON"
    }
    foreach ($key in $diskSourceEvidenceKeys) {
        if ([string]$diskSourceEvidenceHashes[$key] -ne [string]$stdoutSourceEvidenceHashes[$key]) {
            throw "$Context disk JSON source_evidence_file_hashes value for '$key' did not match stdout JSON"
        }
    }
    if ([string]$diskJson.bundle_file_manifest_policy -ne [string]$StdoutResult.bundle_file_manifest_policy) {
        throw "$Context disk JSON bundle_file_manifest_policy did not match stdout JSON"
    }

    foreach ($expected in @(
        "# Calibration Sign-off Evidence",
        "Status:",
        "Acceptance status:",
        "Policy:",
        "Decision hash:",
        "Sign-off hash:",
        "Diff hash:",
        "Before snapshot hash:",
        "After snapshot hash:",
        "Added:",
        "Removed:",
        "Changed:",
        "Unchanged:",
        "## Files",
        "## Reasons"
    )) {
        Assert-TextIncludes -Text $mdText -Expected $expected -Context $Context
    }

    $jsonHash = Get-SHA256Hex -FilePath $jsonPath
    $mdHash = Get-SHA256Hex -FilePath $mdPath
    Assert-SumsContainHash -SumsText $sumsText -ExpectedHash $jsonHash -FileName "calibration_signoff_evidence.json" -Context $Context
    Assert-SumsContainHash -SumsText $sumsText -ExpectedHash $mdHash -FileName "calibration_signoff_evidence.md" -Context $Context
    if ($sumsText -match "(?m)^\S+\s+SHA256SUMS\.txt$") {
        throw "$Context SHA256SUMS.txt must not include a self-hash line"
    }

    if ($diskJson.ContainsKey("file_hashes") -and $null -ne $diskJson.file_hashes -and ($diskJson.file_hashes | Measure-Object).Count -gt 0) {
        throw "$Context JSON must not claim actual bundle file hashes for its own files"
    }

    if (-not $diskJson.ContainsKey("source_evidence_file_hashes")) {
        throw "$Context JSON must contain source_evidence_file_hashes"
    }
    if (-not $diskJson.ContainsKey("bundle_file_manifest_policy")) {
        throw "$Context JSON must contain bundle_file_manifest_policy"
    }
}

function Assert-SignoffJsonResult {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Result,

        [Parameter(Mandatory = $true)]
        [string] $Context,

        [Parameter(Mandatory = $true)]
        [int] $ExpectedExitCode,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedStatus,

        [Parameter(Mandatory = $true)]
        [string] $ExpectedAcceptanceStatus,

        [Parameter(Mandatory = $true)]
        [bool] $ExpectedEvidenceValid
    )

    Assert-NoTraceback -Text $Result.StdErr -Context $Context
    if ($Result.ExitCode -ne $ExpectedExitCode) {
        throw "$Context expected exit code $ExpectedExitCode, got $($Result.ExitCode).`n$($Result.StdOut)`n$($Result.StdErr)"
    }
    if (-not $Result.StdOut) {
        throw "$Context returned empty stdout"
    }

    $parsed = ConvertTo-Hashtable -InputObject (ConvertFrom-Json -InputObject $Result.StdOut)
    Assert-JsonFieldsPresent -Object $parsed -Fields @(
        "status",
        "reasons",
        "acceptance_status",
        "signoff_evidence_type",
        "signoff_evidence_version",
        "policy_id",
        "policy_version",
        "decision_hash",
        "signoff_hash",
        "diff_hash",
        "before_snapshot_hash",
        "after_snapshot_hash",
        "evidence_valid",
        "sha256sums_valid",
        "json_valid",
        "markdown_valid",
        "diff_hash_valid",
        "evidence_cross_checks_valid",
        "files",
        "source_evidence_file_hashes",
        "bundle_file_manifest_policy"
    ) -Context $Context

    if ([string]$parsed.status -ne $ExpectedStatus) { throw "$Context expected status=$ExpectedStatus" }
    if ([string]$parsed.acceptance_status -ne $ExpectedAcceptanceStatus) { throw "$Context expected acceptance_status=$ExpectedAcceptanceStatus" }
    if ([bool]$parsed.evidence_valid -ne $ExpectedEvidenceValid) { throw "$Context expected evidence_valid=$ExpectedEvidenceValid" }
    if ([string]$parsed.signoff_evidence_type -ne "calibration_signoff_evidence") { throw "$Context expected signoff_evidence_type=calibration_signoff_evidence" }
    if ([int]$parsed.signoff_evidence_version -ne 1) { throw "$Context expected signoff_evidence_version=1" }
    if (-not $parsed.reasons -or @($parsed.reasons).Count -eq 0) { throw "$Context expected non-empty reasons" }
    if ([string]$parsed.policy_id -ne "calibration_registry_diff_acceptance_v1") { throw "$Context expected policy_id=calibration_registry_diff_acceptance_v1" }
    if ([int]$parsed.policy_version -ne 1) { throw "$Context expected policy_version=1" }
    if (-not [string]$parsed.signoff_hash) {
        throw "$Context expected non-empty signoff_hash"
    }
    if ($ExpectedEvidenceValid) {
        foreach ($field in @("decision_hash", "diff_hash", "before_snapshot_hash", "after_snapshot_hash")) {
            if (-not [string]$parsed[$field]) {
                throw "$Context expected non-empty $field"
            }
        }
    }
    if (($parsed.files | ConvertTo-Json -Compress) -ne (@(
                "calibration_signoff_evidence.json",
                "calibration_signoff_evidence.md",
                "SHA256SUMS.txt"
            ) | ConvertTo-Json -Compress)) {
        throw "$Context expected exact files array"
    }
    if (-not $parsed.ContainsKey("source_evidence_file_hashes")) {
        throw "$Context expected source_evidence_file_hashes"
    }
    if (-not $parsed.ContainsKey("bundle_file_manifest_policy")) {
        throw "$Context expected bundle_file_manifest_policy"
    }
    Assert-TextIncludes -Text ([string]$parsed.bundle_file_manifest_policy) -Expected "SHA256SUMS.txt" -Context $Context
    Assert-TextIncludes -Text ([string]$parsed.bundle_file_manifest_policy) -Expected "self-referential JSON hashing" -Context $Context

    return $parsed
}

function Invoke-SignoffJson {
    param(
        [Parameter(Mandatory = $true)]
        [string] $EvidenceDir,

        [Parameter(Mandatory = $true)]
        [string] $OutputDir,

        [switch] $Overwrite
    )

    $arguments = @(
        "calibration-signoff-evidence-export",
        "--evidence-dir", $EvidenceDir,
        "--output-dir", $OutputDir
    )
    if ($Overwrite) {
        $arguments += "--overwrite"
    }
    return Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments $arguments
}

function Copy-Evidence {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,

        [Parameter(Mandatory = $true)]
        [string] $SourceDir,

        [Parameter(Mandatory = $true)]
        [string] $DestinationRoot
    )

    $dest = Join-Path $DestinationRoot $Name
    Copy-Item -Path $SourceDir -Destination $dest -Recurse -Force
    return $dest
}

$helpResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("--help")
if ($helpResult.ExitCode -ne 0) {
    $details = if ($helpResult.StdErr) { $helpResult.StdErr } else { $helpResult.StdOut }
    throw "lawful-anomaly --help failed.`n$details"
}

$baseTempRoot = Join-Path $env:TEMP ("phase26-calibration-signoff-evidence-bundle-release-" + [guid]::NewGuid().ToString())
$readyFlowRoot = Join-Path $baseTempRoot "ready"
$incompleteFlowRoot = Join-Path $baseTempRoot "incomplete"
$deniedFlowRoot = Join-Path $baseTempRoot "denied"
$registryFlowRoot = Join-Path $baseTempRoot "registry"
$emptyRegistryRoot = Join-Path $baseTempRoot "empty-registry"
$invalidFlowRoot = Join-Path $baseTempRoot "invalid"
$signoffRoot = Join-Path $baseTempRoot "signoff"

New-Item -ItemType Directory -Path $readyFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $incompleteFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $deniedFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $registryFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $emptyRegistryRoot -Force | Out-Null
New-Item -ItemType Directory -Path $invalidFlowRoot -Force | Out-Null
New-Item -ItemType Directory -Path $signoffRoot -Force | Out-Null

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
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase26-generation.sqlite3"

    $initResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($initResult.ExitCode -ne 0) {
        throw "Ready flow init-db failed.`n$($initResult.StdErr)"
    }

    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase26-signoff-ready-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null

    $executeRun = Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase26-signoff-ready-001")
    $candidateCount = [int]$executeRun.candidate_count
    $topReviewWindow = [Math]::Min($candidateCount, 20)
    $requiredReviewCount = [Math]::Max(
        [int][Math]::Ceiling($candidateCount * 0.20),
        [int][Math]::Ceiling($topReviewWindow * 0.50)
    )
    if ($requiredReviewCount -lt 2) {
        $requiredReviewCount = 2
    }

    $reviewCandidates = @(
        Invoke-LawfulJson -Arguments @(
            "review-queue",
            "--run-id", "phase26-signoff-ready-001",
            "--limit", ([string]$requiredReviewCount)
        )
    )

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
            "--run-id", "phase26-signoff-ready-001",
            "--reviewer-id", "phase26-signoff-verifier",
            "--decision", "approve_for_archive_quote",
            "--note", "phase26 approve"
        ) | Out-Null
    }

    foreach ($candidate in @($reviewCandidates | Select-Object -Skip $approveCount -First $watchCount)) {
        Invoke-LawfulJson -Arguments @(
            "review-decide",
            "--candidate-id", ([string]$candidate.candidate_id),
            "--run-id", "phase26-signoff-ready-001",
            "--reviewer-id", "phase26-signoff-verifier",
            "--decision", "watch",
            "--note", "phase26 watch"
        ) | Out-Null
    }

    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase26-signoff-ready-001",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null

    $readyArtifactDir = Join-Path $readyFlowRoot "artifact-ready"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase26-signoff-ready-001",
        "--output-dir", $readyArtifactDir
    ) | Out-Null

    # ============================================================
    # INCOMPLETE ARTIFACT GENERATION
    # ============================================================
    Set-Location $incompleteFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $incompleteFlowRoot "phase26-incomplete.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase26-signoff-incomplete-001",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase26-signoff-incomplete-001") | Out-Null

    $incompleteArtifactDir = Join-Path $incompleteFlowRoot "artifact-incomplete"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase26-signoff-incomplete-001",
        "--output-dir", $incompleteArtifactDir
    ) | Out-Null

    # ============================================================
    # LEGAL-DENIED ARTIFACT GENERATION
    # ============================================================
    Set-Location $deniedFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $deniedFlowRoot "phase26-denied.sqlite3"

    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    $deniedCreateResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "create-run",
        "--run-id", "phase26-signoff-denied-001",
        "--geofence", "clear",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    )
    Assert-NoTraceback -Text $deniedCreateResult.StdErr -Context "Denied create-run"
    if ($deniedCreateResult.ExitCode -eq 0) {
        throw "Legal-denied create-run expected non-zero exit code"
    }

    $deniedArtifactDir = Join-Path $deniedFlowRoot "artifact-denied"
    $deniedExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-export",
        "--run-id", "phase26-signoff-denied-001",
        "--output-dir", $deniedArtifactDir
    )
    Assert-NoTraceback -Text $deniedExportResult.StdErr -Context "Denied export"
    if ($deniedExportResult.ExitCode -eq 0) {
        throw "Legal-denied calibration-label-export expected non-zero exit code"
    }

    # ============================================================
    # FRESH REGISTRY DB
    # ============================================================
    Set-Location $registryFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase26-registry.sqlite3"

    $regInitResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db")
    if ($regInitResult.ExitCode -ne 0) {
        throw "Registry init-db failed.`n$($regInitResult.StdErr)"
    }

    foreach ($artifactDir in @($readyArtifactDir, $incompleteArtifactDir, $deniedArtifactDir)) {
        $registerResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
            "calibration-label-register",
            "--artifact-dir", $artifactDir
        )
        Assert-NoTraceback -Text $registerResult.StdErr -Context "Register $artifactDir"
        if ($registerResult.ExitCode -ne 0) {
            throw "Artifact register failed for $artifactDir.`n$($registerResult.StdErr)"
        }
    }

    # ============================================================
    # EMPTY REGISTRY SNAPSHOT EXPORT
    # ============================================================
    Set-Location $emptyRegistryRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $emptyRegistryRoot "phase26-empty-registry.sqlite3"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null

    $emptySnapshotDir = Join-Path $emptyRegistryRoot "snapshot-empty"
    $emptyExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $emptySnapshotDir
    )
    Assert-NoTraceback -Text $emptyExportResult.StdErr -Context "Empty registry snapshot export"
    if ($emptyExportResult.ExitCode -ne 0) {
        throw "Empty registry snapshot export failed.`n$($emptyExportResult.StdErr)"
    }

    # ============================================================
    # FULL REGISTRY SNAPSHOT EXPORTS
    # ============================================================
    Set-Location $registryFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase26-registry.sqlite3"

    $fullSnapshotDir = Join-Path $registryFlowRoot "snapshot-full"
    $fullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $fullSnapshotDir
    )
    Assert-NoTraceback -Text $fullExportResult.StdErr -Context "Full registry snapshot export"
    if ($fullExportResult.ExitCode -ne 0) {
        throw "Full registry snapshot export failed.`n$($fullExportResult.StdErr)"
    }
    $fullExport = ConvertTo-Hashtable -InputObject (ConvertFrom-Json -InputObject $fullExportResult.StdOut)
    if ([int]$fullExport.artifact_count -ne 3) { throw "Full export expected artifact_count=3" }

    $secondFullSnapshotDir = Join-Path $registryFlowRoot "snapshot-full-second"
    $secondFullExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $secondFullSnapshotDir
    )
    Assert-NoTraceback -Text $secondFullExportResult.StdErr -Context "Second full registry snapshot export"
    if ($secondFullExportResult.ExitCode -ne 0) {
        throw "Second full registry snapshot export failed.`n$($secondFullExportResult.StdErr)"
    }

    # ============================================================
    # PLUS-ONE REGISTRY SNAPSHOT EXPORT
    # ============================================================
    Set-Location $readyFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $readyFlowRoot "phase26-generation.sqlite3"
    Invoke-LawfulJson -Arguments @(
        "create-run",
        "--attestation", "present",
        "--geofence", "clear",
        "--run-id", "phase26-signoff-ready-002",
        "--aoi-path", $sampleAoiPath,
        "--start-date", "2024-01-01",
        "--end-date", "2024-03-31"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @("execute-run", "--run-id", "phase26-signoff-ready-002") | Out-Null
    $queue002 = @(
        Invoke-LawfulJson -Arguments @(
            "review-queue",
            "--run-id", "phase26-signoff-ready-002",
            "--limit", "1"
        )
    )
    Invoke-LawfulJson -Arguments @(
        "review-decide",
        "--candidate-id", ([string]$queue002[0].candidate_id),
        "--run-id", "phase26-signoff-ready-002",
        "--reviewer-id", "phase26-signoff-verifier",
        "--decision", "approve_for_archive_quote",
        "--note", "phase26 approve"
    ) | Out-Null
    Invoke-LawfulJson -Arguments @(
        "export-create",
        "--run-id", "phase26-signoff-ready-002",
        "--audience", "report_pdf",
        "--requested-precision", "restricted"
    ) | Out-Null
    $readyArtifactDir2 = Join-Path $readyFlowRoot "artifact-ready-002"
    Invoke-LawfulJson -Arguments @(
        "calibration-label-export",
        "--run-id", "phase26-signoff-ready-002",
        "--output-dir", $readyArtifactDir2
    ) | Out-Null

    Set-Location $registryFlowRoot
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = Join-Path $registryFlowRoot "phase26-registry.sqlite3"
    $plusOneRegisterResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir2
    )
    Assert-NoTraceback -Text $plusOneRegisterResult.StdErr -Context "Plus-one register"
    if ($plusOneRegisterResult.ExitCode -ne 0) {
        throw "Plus-one register failed.`n$($plusOneRegisterResult.StdErr)"
    }

    $plusOneSnapshotDir = Join-Path $registryFlowRoot "snapshot-plus-one"
    $plusOneExportResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $plusOneSnapshotDir
    )
    Assert-NoTraceback -Text $plusOneExportResult.StdErr -Context "Plus-one registry snapshot export"
    if ($plusOneExportResult.ExitCode -ne 0) {
        throw "Plus-one registry snapshot export failed.`n$($plusOneExportResult.StdErr)"
    }
    $plusOneExport = ConvertTo-Hashtable -InputObject (ConvertFrom-Json -InputObject $plusOneExportResult.StdOut)
    if ([int]$plusOneExport.artifact_count -ne 4) { throw "Plus-one export expected artifact_count=4" }

    # ============================================================
    # CREATE CHANGED EVIDENCE SUPPORT SNAPSHOTS
    # ============================================================
    $changedRegistryDb = Join-Path $invalidFlowRoot "changed-registry.sqlite3"
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = $changedRegistryDb
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    ) | Out-Null

    $modifyScript = @"
import sqlite3
conn = sqlite3.connect(r'$changedRegistryDb')
conn.execute('UPDATE calibration_label_artifacts SET label_count = 99')
conn.commit()
conn.close()
"@
    $modifyScriptPath = Join-Path $invalidFlowRoot "modify_db.py"
    Write-LfText -Path $modifyScriptPath -Content $modifyScript
    $pythonResult = Invoke-ProcessCapture -FilePath "python" -Arguments @($modifyScriptPath)
    if ($pythonResult.ExitCode -ne 0) {
        throw "DB modify script failed.`n$($pythonResult.StdErr)"
    }

    $beforeChangedSnapshotDir = Join-Path $invalidFlowRoot "snapshot-changed-before"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $beforeChangedSnapshotDir
    ) | Out-Null

    $originalRegistryDb = Join-Path $invalidFlowRoot "original-registry.sqlite3"
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    $env:LAWFUL_ANOMALY_DB_PATH = $originalRegistryDb
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @("init-db") | Out-Null
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-register",
        "--artifact-dir", $readyArtifactDir
    ) | Out-Null

    $afterChangedSnapshotDir = Join-Path $invalidFlowRoot "snapshot-changed-after"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-export",
        "--output-dir", $afterChangedSnapshotDir
    ) | Out-Null

    # ============================================================
    # GENERATE REQUIRED DIFF EVIDENCE PACKS
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue

    $evidenceFullFull = Join-Path $invalidFlowRoot "evidence-full-full"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $secondFullSnapshotDir,
        "--output-dir", $evidenceFullFull
    ) | Out-Null

    $evidenceEmptyFull = Join-Path $invalidFlowRoot "evidence-empty-full"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $emptySnapshotDir,
        "--after-snapshot-dir", $fullSnapshotDir,
        "--output-dir", $evidenceEmptyFull
    ) | Out-Null

    $evidencePlusOne = Join-Path $invalidFlowRoot "evidence-plus-one"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $plusOneSnapshotDir,
        "--output-dir", $evidencePlusOne
    ) | Out-Null

    $evidenceFullEmpty = Join-Path $invalidFlowRoot "evidence-full-empty"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $fullSnapshotDir,
        "--after-snapshot-dir", $emptySnapshotDir,
        "--output-dir", $evidenceFullEmpty
    ) | Out-Null

    $evidenceChanged = Join-Path $invalidFlowRoot "evidence-changed"
    Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
        "calibration-label-registry-snapshot-diff-export",
        "--before-snapshot-dir", $afterChangedSnapshotDir,
        "--after-snapshot-dir", $beforeChangedSnapshotDir,
        "--output-dir", $evidenceChanged
    ) | Out-Null

    $missingJsonEvidence = Copy-Evidence -Name "missing-json" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    Remove-Item (Join-Path $missingJsonEvidence "calibration_registry_snapshot_diff.json") -Force

    $tamperedJsonEvidence = Copy-Evidence -Name "tampered-json" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    $tamperedJsonPath = Join-Path $tamperedJsonEvidence "calibration_registry_snapshot_diff.json"
    $tamperedJson = Get-Content $tamperedJsonPath -Raw | ConvertFrom-Json
    $tamperedJson.diff_hash = "tampered"
    Write-LfText -Path $tamperedJsonPath -Content (($tamperedJson | ConvertTo-Json -Depth 20) + "`n")
    Recompute-SHA256SUMS -EvidenceDir $tamperedJsonEvidence

    $tamperedSumsEvidence = Copy-Evidence -Name "tampered-sums" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    $tamperedSumsPath = Join-Path $tamperedSumsEvidence "SHA256SUMS.txt"
    $tamperedSumsText = Read-Utf8Text -Path $tamperedSumsPath
    $tamperedSumsText = $tamperedSumsText -replace "0", "1"
    Write-LfText -Path $tamperedSumsPath -Content $tamperedSumsText

    $lonInjectedEvidence = Copy-Evidence -Name "lon-injected" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    $lonJsonPath = Join-Path $lonInjectedEvidence "calibration_registry_snapshot_diff.json"
    $lonJson = Get-Content $lonJsonPath -Raw | ConvertFrom-Json
    $lonJson.unchanged[0] | Add-Member -NotePropertyName "lon" -NotePropertyValue 1.0 -Force
    Write-LfText -Path $lonJsonPath -Content (($lonJson | ConvertTo-Json -Depth 20) + "`n")
    Recompute-SHA256SUMS -EvidenceDir $lonInjectedEvidence

    $labelsInjectedEvidence = Copy-Evidence -Name "labels-injected" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    $labelsJsonPath = Join-Path $labelsInjectedEvidence "calibration_registry_snapshot_diff.json"
    $labelsJson = Get-Content $labelsJsonPath -Raw | ConvertFrom-Json
    $labelsJson.unchanged[0] | Add-Member -NotePropertyName "labels" -NotePropertyValue @() -Force
    Write-LfText -Path $labelsJsonPath -Content (($labelsJson | ConvertTo-Json -Depth 20) + "`n")
    Recompute-SHA256SUMS -EvidenceDir $labelsInjectedEvidence

    # ============================================================
    # OFFLINE SIGNOFF VERIFICATION ONLY AFTER DB PATH REMOVAL
    # ============================================================
    Remove-Item Env:LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
    if (Test-Path Env:LAWFUL_ANOMALY_DB_PATH) {
        throw "LAWFUL_ANOMALY_DB_PATH must be removed before all signoff commands"
    }

    # ============================================================
    # READY SIGNOFF CASES
    # ============================================================
    $readyCases = @(
        @{ Name = "full-full"; EvidenceDir = $evidenceFullFull; OutputDir = (Join-Path $signoffRoot "ready-full-full") },
        @{ Name = "empty-full"; EvidenceDir = $evidenceEmptyFull; OutputDir = (Join-Path $signoffRoot "ready-empty-full") },
        @{ Name = "full-plus-one"; EvidenceDir = $evidencePlusOne; OutputDir = (Join-Path $signoffRoot "ready-plus-one") }
    )
    $readyResults = @{}
    foreach ($case in $readyCases) {
        $result = Invoke-SignoffJson -EvidenceDir $case.EvidenceDir -OutputDir $case.OutputDir
        $parsed = Assert-SignoffJsonResult -Result $result -Context "Ready signoff $($case.Name)" -ExpectedExitCode 0 -ExpectedStatus "ready" -ExpectedAcceptanceStatus "accepted" -ExpectedEvidenceValid $true
        foreach ($flag in @("sha256sums_valid", "json_valid", "markdown_valid", "diff_hash_valid", "evidence_cross_checks_valid")) {
            if ($parsed[$flag] -ne $true) {
                throw "Ready signoff $($case.Name) expected $flag=true"
            }
        }
        Assert-SignoffBundle -OutputDir $case.OutputDir -StdoutResult $parsed -Context "Ready signoff $($case.Name)"
        $readyResults[$case.Name] = [pscustomobject]@{
            Parsed = $parsed
            OutputDir = $case.OutputDir
            EvidenceDir = $case.EvidenceDir
        }
    }

    # ============================================================
    # REJECTED SIGNOFF CASES
    # ============================================================
    $rejectedCases = @(
        @{ Name = "full-empty"; EvidenceDir = $evidenceFullEmpty; OutputDir = (Join-Path $signoffRoot "rejected-full-empty") },
        @{ Name = "changed"; EvidenceDir = $evidenceChanged; OutputDir = (Join-Path $signoffRoot "rejected-changed") }
    )
    foreach ($case in $rejectedCases) {
        $result = Invoke-SignoffJson -EvidenceDir $case.EvidenceDir -OutputDir $case.OutputDir
        $parsed = Assert-SignoffJsonResult -Result $result -Context "Rejected signoff $($case.Name)" -ExpectedExitCode 1 -ExpectedStatus "rejected" -ExpectedAcceptanceStatus "rejected" -ExpectedEvidenceValid $true
        if ([string]$parsed.status -eq "ready") {
            throw "Rejected signoff $($case.Name) must not be ready"
        }
        Assert-SignoffBundle -OutputDir $case.OutputDir -StdoutResult $parsed -Context "Rejected signoff $($case.Name)"
    }

    # ============================================================
    # INVALID SIGNOFF CASES
    # ============================================================
    $invalidCases = @(
        @{ Name = "missing-json"; EvidenceDir = $missingJsonEvidence; OutputDir = (Join-Path $signoffRoot "invalid-missing-json") },
        @{ Name = "tampered-json"; EvidenceDir = $tamperedJsonEvidence; OutputDir = (Join-Path $signoffRoot "invalid-tampered-json") },
        @{ Name = "tampered-sums"; EvidenceDir = $tamperedSumsEvidence; OutputDir = (Join-Path $signoffRoot "invalid-tampered-sums") },
        @{ Name = "lon-injected"; EvidenceDir = $lonInjectedEvidence; OutputDir = (Join-Path $signoffRoot "invalid-lon-injected") },
        @{ Name = "labels-injected"; EvidenceDir = $labelsInjectedEvidence; OutputDir = (Join-Path $signoffRoot "invalid-labels-injected") }
    )
    foreach ($case in $invalidCases) {
        $result = Invoke-SignoffJson -EvidenceDir $case.EvidenceDir -OutputDir $case.OutputDir
        $parsed = Assert-SignoffJsonResult -Result $result -Context "Invalid signoff $($case.Name)" -ExpectedExitCode 1 -ExpectedStatus "invalid" -ExpectedAcceptanceStatus "invalid" -ExpectedEvidenceValid $false
        if ([string]$parsed.status -eq "ready") {
            throw "Invalid signoff $($case.Name) must not be ready"
        }
        Assert-SignoffBundle -OutputDir $case.OutputDir -StdoutResult $parsed -Context "Invalid signoff $($case.Name)"
    }

    # ============================================================
    # MARKDOWN STDOUT SMOKE
    # ============================================================
    $markdownCases = @(
        @{ Name = "ready"; EvidenceDir = $evidencePlusOne; OutputDir = (Join-Path $signoffRoot "markdown-ready") },
        @{ Name = "rejected"; EvidenceDir = $evidenceFullEmpty; OutputDir = (Join-Path $signoffRoot "markdown-rejected") },
        @{ Name = "invalid"; EvidenceDir = $missingJsonEvidence; OutputDir = (Join-Path $signoffRoot "markdown-invalid") }
    )
    foreach ($case in $markdownCases) {
        $mdResult = Invoke-ProcessCapture -FilePath "lawful-anomaly" -Arguments @(
            "calibration-signoff-evidence-export",
            "--evidence-dir", $case.EvidenceDir,
            "--output-dir", $case.OutputDir,
            "--output", "markdown"
        )
        Assert-NoTraceback -Text $mdResult.StdErr -Context "Markdown signoff $($case.Name)"
        if ($case.Name -eq "ready" -and $mdResult.ExitCode -ne 0) {
            throw "Markdown signoff ready expected exit 0"
        }
        if ($case.Name -ne "ready" -and $mdResult.ExitCode -eq 0) {
            throw "Markdown signoff $($case.Name) expected non-zero exit"
        }
        foreach ($expected in @(
            "# Calibration Sign-off Evidence",
            "Status:",
            "Acceptance status:",
            "Policy:",
            "Decision hash:",
            "Sign-off hash:",
            "Diff hash:",
            "## Files",
            "## Reasons"
        )) {
            Assert-TextIncludes -Text $mdResult.StdOut -Expected $expected -Context "Markdown signoff $($case.Name)"
        }
    }

    # ============================================================
    # SIGNOFF HASH DETERMINISM
    # ============================================================
    $determinismOutA = Join-Path $signoffRoot "determinism-a"
    $determinismOutB = Join-Path $signoffRoot "determinism-b"
    $determinismResultA = Assert-SignoffJsonResult -Result (Invoke-SignoffJson -EvidenceDir $evidencePlusOne -OutputDir $determinismOutA) -Context "Determinism A" -ExpectedExitCode 0 -ExpectedStatus "ready" -ExpectedAcceptanceStatus "accepted" -ExpectedEvidenceValid $true
    $determinismResultB = Assert-SignoffJsonResult -Result (Invoke-SignoffJson -EvidenceDir $evidencePlusOne -OutputDir $determinismOutB) -Context "Determinism B" -ExpectedExitCode 0 -ExpectedStatus "ready" -ExpectedAcceptanceStatus "accepted" -ExpectedEvidenceValid $true
    if ([string]$determinismResultA.signoff_hash -ne [string]$determinismResultB.signoff_hash) {
        throw "Repeated signoff export on same evidence expected identical signoff_hash"
    }

    $copiedEvidenceDir = Copy-Evidence -Name "copied-plus-one-evidence" -SourceDir $evidencePlusOne -DestinationRoot $invalidFlowRoot
    $determinismOutCopied = Join-Path $signoffRoot "determinism-copied"
    $determinismCopied = Assert-SignoffJsonResult -Result (Invoke-SignoffJson -EvidenceDir $copiedEvidenceDir -OutputDir $determinismOutCopied) -Context "Determinism copied" -ExpectedExitCode 0 -ExpectedStatus "ready" -ExpectedAcceptanceStatus "accepted" -ExpectedEvidenceValid $true
    if ([string]$determinismCopied.source_evidence_dir -eq [string]$determinismResultA.source_evidence_dir) {
        throw "Copied evidence expected different source_evidence_dir"
    }
    if ([string]$determinismCopied.signoff_hash -ne [string]$determinismResultA.signoff_hash) {
        throw "Copied evidence expected identical signoff_hash"
    }

    # ============================================================
    # OUTPUT-DIR BEHAVIOR
    # ============================================================
    $nonEmptyOutputDir = Join-Path $signoffRoot "nonempty-output"
    New-Item -ItemType Directory -Path $nonEmptyOutputDir -Force | Out-Null
    Write-LfText -Path (Join-Path $nonEmptyOutputDir "unrelated.txt") -Content "keep"
    $nonEmptyResult = Invoke-SignoffJson -EvidenceDir $evidencePlusOne -OutputDir $nonEmptyOutputDir
    Assert-NoTraceback -Text $nonEmptyResult.StdErr -Context "Non-empty output dir"
    if ($nonEmptyResult.ExitCode -eq 0) { throw "Non-empty output dir expected non-zero exit code" }
    $nonEmptyParsed = ConvertTo-Hashtable -InputObject (ConvertFrom-Json -InputObject $nonEmptyResult.StdOut)
    if ([string]$nonEmptyParsed.status -ne "invalid") { throw "Non-empty output dir expected status=invalid" }
    if (-not (Test-Path (Join-Path $nonEmptyOutputDir "unrelated.txt"))) {
        throw "Non-empty output dir must preserve unrelated files"
    }

    $overwriteOutputDir = Join-Path $signoffRoot "overwrite-output"
    New-Item -ItemType Directory -Path $overwriteOutputDir -Force | Out-Null
    Write-LfText -Path (Join-Path $overwriteOutputDir "unrelated.txt") -Content "keep"
    foreach ($name in @("calibration_signoff_evidence.json", "calibration_signoff_evidence.md", "SHA256SUMS.txt")) {
        Write-LfText -Path (Join-Path $overwriteOutputDir $name) -Content "old"
    }
    $overwriteResult = Assert-SignoffJsonResult -Result (Invoke-SignoffJson -EvidenceDir $evidencePlusOne -OutputDir $overwriteOutputDir -Overwrite) -Context "Overwrite output dir" -ExpectedExitCode 0 -ExpectedStatus "ready" -ExpectedAcceptanceStatus "accepted" -ExpectedEvidenceValid $true
    Assert-SignoffBundle -OutputDir $overwriteOutputDir -StdoutResult $overwriteResult -Context "Overwrite output dir"
    if (-not (Test-Path (Join-Path $overwriteOutputDir "unrelated.txt"))) {
        throw "Overwrite must preserve unrelated files"
    }
    if ((Read-Utf8Text -Path (Join-Path $overwriteOutputDir "calibration_signoff_evidence.json")) -eq "old") {
        throw "Overwrite must replace known output files"
    }

    # ============================================================
    # OFFLINE PROOF
    # ============================================================
    if (Test-Path Env:LAWFUL_ANOMALY_DB_PATH) {
        throw "LAWFUL_ANOMALY_DB_PATH must remain removed during signoff verification"
    }

    # ============================================================
    # OUTSIDE-CWD SAFETY CHECKS
    # ============================================================
    foreach ($flowRoot in @($readyFlowRoot, $incompleteFlowRoot, $deniedFlowRoot, $registryFlowRoot, $emptyRegistryRoot, $invalidFlowRoot, $signoffRoot)) {
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

Write-Host "Phase 26 calibration signoff evidence bundle release verification passed."
