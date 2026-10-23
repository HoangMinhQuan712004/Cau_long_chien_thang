<#
.SYNOPSIS
  Prepare the 6-session Claude team: board, git worktrees, per-role databases,
  env files, Python venvs and node_modules. Safe to re-run (skips what exists).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .claude\team\setup-team.ps1
  powershell -ExecutionPolicy Bypass -File .claude\team\setup-team.ps1 -DryRun
  powershell -ExecutionPolicy Bypass -File .claude\team\setup-team.ps1 -SkipInstall

.NOTES
  Run from anywhere. Requires: git, Docker Desktop running, Python 3.15 (py -3.15), Node 26 + npm.
  Read .claude/team/PROTOCOL.md for how the sessions work together.
#>
param(
    [string]$TeamRoot = "E:\caulong-team",
    [switch]$SkipInstall,
    [switch]$DryRun
)

# Native tools (docker, git, npm) write progress to stderr; with "Stop" PowerShell 5.1 would abort on it.
# So we continue on stderr and check exit codes explicitly.
$ErrorActionPreference = "Continue"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Compose = @("compose", "-f", (Join-Path $Repo "docker-compose.yml"))
$Board = Join-Path $TeamRoot "board"

# role -> settings (RELEASE uses the main repo checkout, ARCHITECT/DOCS need no runtime)
$Roles = [ordered]@{
    "architect" = @{ Db = $null;         ApiPort = $null; WebPort = $null; Runtime = $false }
    "backend"   = @{ Db = "caulong_be";  ApiPort = 8101;  WebPort = $null; Runtime = $true }
    "frontend"  = @{ Db = "caulong_fe";  ApiPort = 8102;  WebPort = 3102;  Runtime = $true }
    "qa"        = @{ Db = "caulong_qa";  ApiPort = 8103;  WebPort = 3103;  Runtime = $true }
    "docs"      = @{ Db = $null;         ApiPort = $null; WebPort = $null; Runtime = $false }
}
$StateNames = "ARCHITECT", "BACKEND", "FRONTEND", "QA", "DOCS-STEWARD", "RELEASE-INTEGRATION"

function Step([string]$msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Run([string]$what, [scriptblock]$action) {
    if ($DryRun) { Write-Host "  [dry-run] $what"; return }
    Write-Host "  $what"
    $global:LASTEXITCODE = 0
    & $action
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "Failed: $what (exit $LASTEXITCODE)" }
}
function Write-Utf8NoBom([string]$path, [string]$text) {
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

Step "Checking prerequisites"
git --version | Out-Null
docker info --format "{{.ServerVersion}}" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running - start Docker Desktop first." }
$py = (py -3.15 --version 2>&1) | Out-String
if ($LASTEXITCODE -ne 0 -or $py -notmatch "3\.15") { throw "Python 3.15 not found (py -3.15). Install it first." }
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 26) { Write-Warning "Node $(node --version) < 26. Run 'nvm use 26.12.1' (admin PowerShell)." }
Write-Host "  repo: $Repo | $($py.Trim()) | node $(node --version)"

Step "Board at $Board"
foreach ($d in "tasks", "decisions", "messages", "state", "qa", "releases") {
    $p = Join-Path $Board $d
    if (-not (Test-Path $p)) { Run "mkdir $p" { New-Item -ItemType Directory -Force $p -ErrorAction Stop | Out-Null } }
}
$boardFile = Join-Path $Board "BOARD.md"
if (-not (Test-Path $boardFile)) {
    Run "create BOARD.md" {
        Write-Utf8NoBom $boardFile ("# BOARD - chi ARCHITECT sua`n`n" +
            "| ID | Viec | Vai | Trang thai | Nhanh | Ghi chu |`n|---|---|---|---|---|---|`n")
    }
}
foreach ($n in $StateNames) {
    $f = Join-Path $Board "state\$n.md"
    if (-not (Test-Path $f)) {
        Run "create state\$n.md" {
            Write-Utf8NoBom $f "# $n`n`nlast_read: (none)`ncurrent_task: (none)`nnotes:`n"
        }
    }
}

Step "Git worktrees in $TeamRoot (detached at origin/main)"
Run "git fetch origin" { git -C $Repo fetch -q origin }
foreach ($role in $Roles.Keys) {
    $wt = Join-Path $TeamRoot $role
    if (Test-Path $wt) { Write-Host "  exists: $wt"; continue }
    Run "git worktree add $wt" { git -C $Repo worktree add -q --detach $wt origin/main }
}

Step "Per-role databases (shared Postgres container)"
Run "docker compose up -d db redis" { docker @Compose up -d db redis 2>&1 | Out-Null }
if (-not $DryRun) {
    for ($i = 0; $i -lt 30; $i++) {
        docker @Compose exec -T db pg_isready -U caulong 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
}
foreach ($role in $Roles.Keys) {
    $db = $Roles[$role].Db
    if (-not $db) { continue }
    foreach ($name in $db, "${db}_test") {
        $exists = if ($DryRun) { "" } else {
            docker @Compose exec -T db psql -U caulong -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'" 2>&1
        }
        if ("$exists".Trim() -eq "1") { Write-Host "  exists: $name"; continue }
        Run "create database $name" {
            docker @Compose exec -T db psql -U caulong -d postgres -c "CREATE DATABASE $name" 2>&1 | Out-Null
        }
    }
}

Step "Env files per worktree (copied from main repo, own DB/ports)"
$baseEnv = Join-Path $Repo "backend\.env"
if (-not (Test-Path $baseEnv)) { throw "Missing $baseEnv - create it from backend\.env.example first." }
foreach ($role in $Roles.Keys) {
    $cfg = $Roles[$role]
    if (-not $cfg.Runtime) { continue }
    $wt = Join-Path $TeamRoot $role
    $envFile = Join-Path $wt "backend\.env"
    if (-not (Test-Path $envFile)) {
        Run "write $role\backend\.env (DB $($cfg.Db))" {
            $lines = Get-Content $baseEnv | ForEach-Object {
                if ($_ -match '^DATABASE_URL=(.*/)[^/]+$') { "DATABASE_URL=$($Matches[1])$($cfg.Db)" } else { $_ }
            }
            Write-Utf8NoBom $envFile (($lines -join "`n") + "`n")
        }
    }
    $feEnv = Join-Path $wt "frontend\.env.local"
    if (-not (Test-Path $feEnv)) {
        $web = if ($cfg.WebPort) { $cfg.WebPort } else { 3000 }
        Run "write $role\frontend\.env.local (API $($cfg.ApiPort))" {
            Write-Utf8NoBom $feEnv "BACKEND_URL=http://localhost:$($cfg.ApiPort)`nNEXT_PUBLIC_SITE_URL=http://localhost:$web`n"
        }
    }
}

if (-not $SkipInstall) {
    Step "Install Python venv + node_modules, migrate and seed role databases"
    foreach ($role in $Roles.Keys) {
        if (-not $Roles[$role].Runtime) { continue }
        $be = Join-Path $TeamRoot "$role\backend"
        $fe = Join-Path $TeamRoot "$role\frontend"
        if (-not (Test-Path (Join-Path $be ".venv"))) {
            Run "[$role] python venv" { Push-Location $be; try { py -3.15 -m venv .venv } finally { Pop-Location } }
        }
        Run "[$role] pip install" {
            Push-Location $be
            try { & .\.venv\Scripts\python.exe -m pip install -q -e ".[dev]" } finally { Pop-Location }
        }
        Run "[$role] alembic upgrade + seed" {
            Push-Location $be
            try {
                & .\.venv\Scripts\alembic.exe upgrade head 2>&1 | Out-Null
                & .\.venv\Scripts\python.exe -m app.scripts.seed | Out-Null
            } finally { Pop-Location }
        }
        if (-not (Test-Path (Join-Path $fe "node_modules"))) {
            Run "[$role] npm ci" { Push-Location $fe; try { npm ci --no-audit --no-fund 2>&1 | Out-Null } finally { Pop-Location } }
        }
    }
}

Step "Done. Open 6 terminals and run one command in each:"
$add = "--add-dir `"$Board`""
@(
    @("ARCHITECT", (Join-Path $TeamRoot "architect"), "architect", "opus"),
    @("BACKEND", (Join-Path $TeamRoot "backend"), "backend", "opus"),
    @("FRONTEND", (Join-Path $TeamRoot "frontend"), "frontend", "sonnet"),
    @("QA", (Join-Path $TeamRoot "qa"), "qa", "sonnet"),
    @("DOCS-STEWARD", (Join-Path $TeamRoot "docs"), "docs-steward", "sonnet"),
    @("RELEASE-INTEGRATION", $Repo, "release-integration", "sonnet")
) | ForEach-Object {
    Write-Host ("  {0,-20} cd `"{1}`"; claude --agent {2} --model {3} -n {0} {4}" -f $_[0], $_[1], $_[2], $_[3], $add)
}
