<#
.SYNOPSIS
  Switch the production site to a new domain: DNS check, Caddy + HTTPS,
  app config, GitHub SITE_URL, redeploy and verify.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\set-domain.ps1 -Domain caulongabc.com

.NOTES
  Prerequisites: DNS A record "@" (and optionally "www") -> server IP,
  SSH key access as root, GitHub CLI logged in (gh auth status).
#>
param(
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$ServerIp = "103.20.97.195",
    [string]$SshUser = "root",
    [string]$Repo = "HoangMinhQuan712004/Cau_long_chien_thang"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Assert-Ok([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

function Get-ARecords([string]$name) {
    try {
        @(Resolve-DnsName -Name $name -Type A -Server 1.1.1.1 -DnsOnly -ErrorAction Stop |
            Where-Object { $_.Type -eq "A" } | ForEach-Object { $_.IPAddress })
    } catch { @() }
}

$Domain = ($Domain.Trim().ToLower() -replace "^https?://", "") -replace "/.*$", ""
if ($Domain -notmatch "^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$") {
    throw "Invalid domain: $Domain"
}
$target = "$SshUser@$ServerIp"
$oldHost = ($ServerIp -replace "\.", "-") + ".sslip.io"

Write-Host "`n[1/4] Checking DNS for $Domain" -ForegroundColor Cyan
$apex = Get-ARecords $Domain
if ($apex -notcontains $ServerIp) {
    throw "$Domain -> '$($apex -join ', ')' (expected $ServerIp). Add A record '@' -> $ServerIp, wait a few minutes, retry."
}
$withWww = (Get-ARecords "www.$Domain") -contains $ServerIp
if ($withWww) { Write-Host "  www.$Domain OK (will redirect to $Domain)" }
else { Write-Warning "www.$Domain does not point to $ServerIp - skipping www." }

Write-Host "`n[2/4] Configuring server (Caddy, HTTPS, app env)" -ForegroundColor Cyan
scp -q (Join-Path $PSScriptRoot "set-domain-remote.sh") "${target}:/tmp/set-domain-remote.sh"
Assert-Ok "scp"
ssh $target "bash /tmp/set-domain-remote.sh $Domain $([int]$withWww) $oldHost; rc=`$?; rm -f /tmp/set-domain-remote.sh; exit `$rc"
Assert-Ok "Server configuration"

Write-Host "`n[3/4] Updating GitHub SITE_URL and redeploying (rebuilds web image)" -ForegroundColor Cyan
gh variable set SITE_URL --repo $Repo --body "https://$Domain"
Assert-Ok "gh variable set"
$before = gh run list --repo $Repo --workflow CD --limit 1 --json databaseId --jq ".[0].databaseId"
gh workflow run CD --repo $Repo --ref main
Assert-Ok "gh workflow run"
$runId = $before
for ($i = 0; $i -lt 40 -and $runId -eq $before; $i++) {
    Start-Sleep -Seconds 3
    $runId = gh run list --repo $Repo --workflow CD --limit 1 --json databaseId --jq ".[0].databaseId"
}
if ($runId -eq $before) { throw "CD run did not start" }
Write-Host "  https://github.com/$Repo/actions/runs/$runId"
gh run watch $runId --repo $Repo --exit-status --interval 15 | Out-Null
Assert-Ok "CD deploy"

Write-Host "`n[4/4] Verifying https://$Domain" -ForegroundColor Cyan
$html = (Invoke-WebRequest -UseBasicParsing "https://$Domain/").Content
$canonical = [regex]::Match($html, '<link rel="canonical" href="([^"]+)"').Groups[1].Value
if ($canonical -notlike "https://$Domain*") { throw "Canonical is '$canonical', expected https://$Domain" }
Write-Host "  canonical: $canonical"
Write-Host "`nDone: https://$Domain" -ForegroundColor Green
Write-Host "Next: add the site to Google Search Console and submit https://$Domain/sitemap.xml"
