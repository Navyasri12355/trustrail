"""
Dump the TrustRail database to backups/.

Usage (from repo root):
  powershell -File scripts/backup_db.ps1
  powershell -File scripts/backup_db.ps1 -Restore backups/trustrail_YYYYMMDD_HHMMSS.sql
"""

param(
    [string]$Restore = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$BackupDir = Join-Path $Root "backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Load-DotEnv {
    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) { return }
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2 -and -not [string]::IsNullOrWhiteSpace($parts[0])) {
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
}

Load-DotEnv

$PgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "trustrail" }
$PgDb   = if ($env:POSTGRES_DB)   { $env:POSTGRES_DB }   else { "trustrail" }

$dockerUp = $false
try {
    $null = docker compose ps --status running db 2>$null
    if ($LASTEXITCODE -eq 0) {
        $running = docker compose ps --status running --format json db 2>$null
        $dockerUp = [bool]$running
    }
} catch {
    $dockerUp = $false
}

if ($Restore) {
    if (-not (Test-Path $Restore)) { throw "Backup file not found: $Restore" }
    if ($dockerUp) {
        Write-Host "Restoring $Restore into Postgres (docker compose db)..."
        Get-Content -Raw $Restore | docker compose exec -T db psql -U $PgUser -d $PgDb
        Write-Host "Restore complete."
        return
    }
    $sqliteDb = Join-Path $Root "trustrail.db"
    Copy-Item $Restore $sqliteDb -Force
    Write-Host "Restored SQLite file to $sqliteDb"
    return
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"

if ($dockerUp) {
    $out = Join-Path $BackupDir "trustrail_$stamp.sql"
    Write-Host "Dumping Postgres to $out ..."
    docker compose exec -T db pg_dump -U $PgUser $PgDb | Set-Content -Encoding utf8 $out
    Write-Host "Wrote $out"
    return
}

$sqliteDb = Join-Path $Root "trustrail.db"
if (Test-Path $sqliteDb) {
    $out = Join-Path $BackupDir "trustrail_$stamp.db"
    Copy-Item $sqliteDb $out
    Write-Host "Copied SQLite DB to $out"
    return
}

throw "No running Compose Postgres service and no trustrail.db found. Start the stack or create a local DB first."
