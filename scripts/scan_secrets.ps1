#Requires -Version 5.1
<#
.SYNOPSIS
  Scan git-tracked files for high-signal secret patterns (PowerShell).

.DESCRIPTION
  Uses git grep on the index / working tree. Exits 1 if any pattern matches.
  Run from repo root or any folder (script cd's to repo root).

.EXAMPLE
  pwsh -File scripts/scan_secrets.ps1
  .\scripts\scan_secrets.ps1
#>
$ErrorActionPreference = 'Continue'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $RepoRoot

git rev-parse --git-dir 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Not inside a git repository. Run from the ai-hedge-fund repo (or clone root).' -ForegroundColor Red
    exit 2
}

$Excludes = @(
    ':(exclude).env.example'
    ':(exclude)scripts/scan_secrets.ps1'
)

$ScanFailed = $false

function ConvertTo-GitGrepLineArray {
    param($Raw)
    if ($null -eq $Raw) { return @() }
    if ($Raw -is [System.Array]) { return [string[]]$Raw }
    return [string[]](($Raw -split "`r?`n").Where({ $_.Length -gt 0 }))
}

function Write-ScanMatch {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string[]]$Lines
    )
    Write-Host ''
    Write-Host "==> Possible secret: $Title"
    foreach ($line in $Lines) { Write-Host $line }
    $script:ScanFailed = $true
}

function Invoke-GitSecretRegex {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Pattern
    )
    # Use -E <pattern> (portable); --regexp= is not supported on all Git for Windows builds.
    $gitArgs = @('grep', '--no-color', '--line-number', '-E', $Pattern, '--') + $Excludes
    $out = & git @gitArgs 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) {
        Write-ScanMatch -Title $Title -Lines (ConvertTo-GitGrepLineArray $out)
    }
}

Write-Host 'Scanning tracked files for common credential patterns...'

Invoke-GitSecretRegex -Title 'OpenAI project key (sk-proj-...)' -Pattern 'sk-proj-[A-Za-z0-9_-]{20,}'
Invoke-GitSecretRegex -Title 'Anthropic API key (sk-ant-api...)' -Pattern 'sk-ant-api03-[A-Za-z0-9_-]{20,}'
Invoke-GitSecretRegex -Title 'GitHub classic PAT (ghp_...)' -Pattern 'ghp_[A-Za-z0-9]{36,}'
Invoke-GitSecretRegex -Title 'GitHub fine-grained PAT (github_pat_...)' -Pattern 'github_pat_[A-Za-z0-9_]{20,}'
Invoke-GitSecretRegex -Title 'Google API key (AIza...)' -Pattern 'AIza[0-9A-Za-z_-]{35}'
Invoke-GitSecretRegex -Title 'Slack bot token (xox...)' -Pattern 'xox[baprs]-[0-9a-zA-Z-]{10,}'
Invoke-GitSecretRegex -Title 'Stripe live secret (sk_live_...)' -Pattern 'sk_live_[0-9a-zA-Z]{20,}'
Invoke-GitSecretRegex -Title 'Stripe restricted live (rk_live_...)' -Pattern 'rk_live_[0-9a-zA-Z]{20,}'
Invoke-GitSecretRegex -Title 'AWS access key id (AKIA...)' -Pattern 'AKIA[0-9A-Z]{16}'
Invoke-GitSecretRegex -Title 'PEM/OpenSSH private key header' -Pattern '^-----BEGIN[[:space:]].*PRIVATE[[:space:]]+KEY-----'

$fdArgs = @(
    'grep', '--no-color', '--line-number', '-E',
    '^[[:space:]]*FINANCIAL_DATASETS_API_KEY=[^[:space:]#]+',
    '--'
) + $Excludes
$fdOut = & git @fdArgs 2>$null
if ($LASTEXITCODE -eq 0 -and $fdOut) {
    $fdLines = ConvertTo-GitGrepLineArray $fdOut
    $filtered = @($fdLines | Where-Object {
            $_ -notmatch 'your-financial-datasets-api-key|example|changeme|placeholder|xxxxxxxx'
        })
    if ($filtered.Count -gt 0) {
        Write-ScanMatch -Title 'FINANCIAL_DATASETS_API_KEY assignment (non-placeholder)' -Lines $filtered
    }
}

if ($ScanFailed) {
    Write-Host ''
    Write-Host 'scan_secrets.ps1: FAILED — remove or rotate the above material before pushing.' -ForegroundColor Red
    exit 1
}

Write-Host 'scan_secrets.ps1: OK (no high-signal secret patterns in tracked files).' -ForegroundColor Green
exit 0
