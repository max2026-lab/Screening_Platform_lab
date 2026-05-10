# V1.11 Release Evidence Index Verifier Release Verification Script
# Offline only. No live STAC. No network. No DB required.

$ErrorActionPreference = "Stop"
$repoRoot = Get-Location

$cliPath = Join-Path $repoRoot ".venv\Scripts\lawful-anomaly.exe"
if (-not (Test-Path $cliPath)) {
    throw "Repo-local CLI not found: $cliPath"
}
Write-Host "Using lawful-anomaly: $cliPath"

# 1. Source contract checks
$cliSource = Get-Content (Join-Path $repoRoot "src\lawful_anomaly_screening\cli.py") -Raw
$evidenceIndexSource = Get-Content (Join-Path $repoRoot "src\lawful_anomaly_screening\releases\evidence_index_verifier.py") -Raw

if ($cliSource -notmatch 'release-evidence-index-verify') {
    throw "cli.py missing release-evidence-index-verify command"
}

$requiredFunctions = @(
    "verify_release_evidence_index",
    "discover_evidence_dirs",
    "load_evidence_list",
    "render_release_evidence_index_markdown",
    "verify_release_evidence",
    "index_hash"
)
foreach ($func in $requiredFunctions) {
    if ($evidenceIndexSource -notmatch $func) {
        throw "evidence_index_verifier.py missing required function: $func"
    }
}

# 2. Targeted tests
Write-Host "Running targeted tests..."
& uv run pytest tests/integration/test_release_evidence_index_verify_cli.py | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Targeted tests failed"
}

# 3. Generate Phase 28 evidence
Write-Host "Generating Phase 28 evidence..."
& powershell -ExecutionPolicy Bypass -File scripts\verify_phase28_full_release_evidence_manifest.ps1 -Overwrite -AllowNonMain | Out-String
if ($LASTEXITCODE -ne 0) {
    throw "Phase 28 evidence generation failed"
}

# 4. Operator smoke using generated evidence
$tempRoot = "C:\temp\screening-v1-11-release-evidence-index-verifier-release"
if (Test-Path $tempRoot) {
    Remove-Item -Recurse -Force $tempRoot
}
New-Item -ItemType Directory -Path $tempRoot | Out-Null

$evidenceSource = Join-Path $repoRoot ".release-evidence\phase28-full-release-evidence-manifest"
$v10Dir = Join-Path $tempRoot "v1.10.0"
$v11Dir = Join-Path $tempRoot "v1.11.0-candidate"
Copy-Item -Recurse $evidenceSource $v10Dir
Copy-Item -Recurse $evidenceSource $v11Dir

Write-Host "Running root mode smoke..."
$rootResult = & $cliPath release-evidence-index-verify --evidence-root $tempRoot 2>&1
$rootExit = $LASTEXITCODE
if ($rootExit -ne 0) {
    throw "Root mode smoke failed with exit $rootExit.`n$rootResult"
}
$rootJson = $rootResult | ConvertFrom-Json
if ($rootJson.status -ne "pass") {
    throw "Root mode smoke status is not pass.`n$rootResult"
}
if ($rootJson.evidence_dir_count -ne 2) {
    throw "Expected evidence_dir_count 2, got $($rootJson.evidence_dir_count)"
}
if ($rootJson.passed_count -ne 2) {
    throw "Expected passed_count 2, got $($rootJson.passed_count)"
}
if ($rootJson.failed_count -ne 0) {
    throw "Expected failed_count 0, got $($rootJson.failed_count)"
}
if ($rootJson.checked_file_count -ne 4) {
    throw "Expected checked_file_count 4, got $($rootJson.checked_file_count)"
}
if (-not $rootJson.index_hash) {
    throw "index_hash is missing"
}

# 5. Evidence-list smoke
$listPath = Join-Path $tempRoot "evidence-list.txt"
$listContent = "`n# comment`n$v10Dir`n$v11Dir`n"
Set-Content -Path $listPath -Value $listContent -Encoding UTF8 -NoNewline

Write-Host "Running evidence-list smoke..."
$listResult = & $cliPath release-evidence-index-verify --evidence-list $listPath 2>&1
$listExit = $LASTEXITCODE
if ($listExit -ne 0) {
    throw "Evidence-list smoke failed with exit $listExit.`n$listResult"
}
$listJson = $listResult | ConvertFrom-Json
if ($listJson.status -ne "pass") {
    throw "Evidence-list smoke status is not pass.`n$listResult"
}
if ($listJson.evidence_dir_count -ne 2) {
    throw "Evidence-list smoke expected evidence_dir_count 2, got $($listJson.evidence_dir_count)"
}

# 6. Markdown smoke
Write-Host "Running markdown smoke..."
$mdResult = & $cliPath release-evidence-index-verify --evidence-root $tempRoot --output markdown 2>&1
$mdExit = $LASTEXITCODE
if ($mdExit -ne 0) {
    throw "Markdown smoke failed with exit $mdExit.`n$mdResult"
}
$mdText = $mdResult | Out-String
if ($mdText -notmatch 'Release Evidence Index Verification') {
    throw "Markdown smoke missing expected header"
}
if ($mdText -notmatch 'Status: `pass`') {
    throw "Markdown smoke missing expected status"
}
if ($mdText -notmatch 'Index hash') {
    throw "Markdown smoke missing expected index hash"
}

# 7. No DB regression
Write-Host "Running no-DB regression..."
$env:LAWFUL_ANOMALY_DB_PATH = Join-Path $tempRoot "nonexistent.sqlite3"
$noDbResult = & $cliPath release-evidence-index-verify --evidence-root $tempRoot 2>&1
$noDbExit = $LASTEXITCODE
Remove-Item Env:\LAWFUL_ANOMALY_DB_PATH -ErrorAction SilentlyContinue
if ($noDbExit -ne 0) {
    throw "No-DB regression failed with exit $noDbExit.`n$noDbResult"
}
$noDbJson = $noDbResult | ConvertFrom-Json
if ($noDbJson.status -ne "pass") {
    throw "No-DB regression status is not pass.`n$noDbResult"
}

# 8. Negative smoke
Write-Host "Running negative smoke..."
$badSums = Join-Path $v11Dir "SHA256SUMS.txt"
$badSumsContent = Get-Content $badSums -Raw
$badSumsContent -replace '^[0-9a-f]{64}', ('0' * 64) | Set-Content $badSums -Encoding UTF8 -NoNewline

$negResult = & $cliPath release-evidence-index-verify --evidence-root $tempRoot 2>&1
$negExit = $LASTEXITCODE
if ($negExit -eq 0) {
    throw "Negative smoke expected non-zero exit, got 0.`n$negResult"
}
$negJson = $negResult | ConvertFrom-Json
if ($negJson.status -ne "fail") {
    throw "Negative smoke status is not fail.`n$negResult"
}
if ($negJson.failed_count -ne 1) {
    throw "Negative smoke expected failed_count 1, got $($negJson.failed_count)"
}

# Restore tampered file
$badSumsContent | Set-Content $badSums -Encoding UTF8 -NoNewline

# 9. Duplicate list smoke
Write-Host "Running duplicate list smoke..."
$dupPath = Join-Path $tempRoot "duplicate-list.txt"
$dupContent = "$v10Dir`n$v10Dir`n"
Set-Content -Path $dupPath -Value $dupContent -Encoding UTF8 -NoNewline

$dupResult = & $cliPath release-evidence-index-verify --evidence-list $dupPath 2>&1
$dupExit = $LASTEXITCODE
if ($dupExit -eq 0) {
    throw "Duplicate list smoke expected non-zero exit, got 0.`n$dupResult"
}
$dupJson = $dupResult | ConvertFrom-Json
if (-not ($dupJson.reasons | Where-Object { $_ -match 'Duplicate evidence directory' })) {
    throw "Duplicate list smoke missing expected reason.`n$dupResult"
}

# 10. Final repo cleanliness
$repoStatus = git status --porcelain
if ($repoStatus) {
    throw "Repository is not clean after verification.`n$repoStatus"
}

$remoteOutput = git remote -v
$forbiddenPatterns = @("x-access-token", "ghp_", "github_pat_", "oauth", "token@")
foreach ($pattern in $forbiddenPatterns) {
    if ($remoteOutput -match $pattern) {
        throw "git remote -v contains forbidden pattern: $pattern"
    }
}

Write-Host "V1.11 release evidence index verifier release verification passed."
