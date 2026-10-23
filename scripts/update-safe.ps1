param(
    [switch]$Force,
    [switch]$SkipTests,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

function Invoke-Step([string]$Label, [scriptblock]$Action) {
    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

$PreviousCommit = (git rev-parse HEAD).Trim()
if (-not $PreviousCommit) { throw "Cannot resolve current git commit." }

try {
    $active = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/streamcopy/jobs?active=1&limit=1" -TimeoutSec 2
    if (($active.jobs | Measure-Object).Count -gt 0 -and -not $Force) {
        throw "Active StreamCopy job detected. Finish it first or rerun with -Force."
    }
} catch {
    if ($_.Exception.Message -like "Active StreamCopy job detected*") { throw }
    Write-Host "Backend health check unavailable; continuing with filesystem snapshot." -ForegroundColor Yellow
}

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $Python) {
    $Snapshot = (& $Python "scripts\snapshot_state.py").Trim()
} else {
    $Snapshot = (& uv run python "scripts\snapshot_state.py").Trim()
}
if (-not $Snapshot) { throw "State snapshot did not return a path." }
Write-Host "Snapshot: $Snapshot" -ForegroundColor Green

try {
    Invoke-Step "Fetch origin" { git fetch origin }
    $TargetCommit = (git rev-parse "origin/$Branch").Trim()
    if (-not $TargetCommit) { throw "Cannot resolve origin/$Branch." }

    Write-Host "Previous: $PreviousCommit"
    Write-Host "Target:   $TargetCommit"

    Invoke-Step "Switch runtime atomically to fetched commit" {
        git reset --hard "origin/$Branch"
    }
    Invoke-Step "Install frontend dependencies" {
        npm --prefix frontend install
    }
    Invoke-Step "Build frontend" {
        npm run build
    }

    if (-not $SkipTests) {
        Invoke-Step "Sync Python dev environment" {
            uv sync --group dev
        }
        Invoke-Step "Backend lint" {
            uv run ruff check backend tests
        }
        Invoke-Step "Backend tests" {
            uv run pytest -q
        }
        Invoke-Step "Frontend lint" {
            npm run ui:lint
        }
    }

    Write-Host ""
    Write-Host "DiskShell update validated." -ForegroundColor Green
    Write-Host "Snapshot: $Snapshot"
    Write-Host "Start:    .\scripts\start-admin.ps1"
} catch {
    Write-Host ""
    Write-Host "Update failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Rolling runtime back to $PreviousCommit ..." -ForegroundColor Yellow
    git reset --hard $PreviousCommit | Out-Host
    try { npm run build | Out-Host } catch {}
    Write-Host "Runtime rollback complete." -ForegroundColor Yellow
    Write-Host "State snapshot was not modified: $Snapshot"
    throw
}
