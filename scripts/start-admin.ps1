param(
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# RU: Корень проекта определяется относительно этого скрипта.
# EN: Resolve the project root relative to this script.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

if (-not (Test-IsAdministrator)) {
    # RU: Повышаем только backend-процесс через стандартный UAC.
    # EN: Elevate only the backend process through the standard UAC prompt.
    $escapedScript = $PSCommandPath.Replace("'", "''")
    $command = "& '$escapedScript' -NoPause"
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NoExit",
        "-Command", $command
    )
    exit 0
}

Set-Location $ProjectRoot

Write-Host ""
Write-Host "DiskShell backend / elevated Administrator runtime" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "URL:     http://127.0.0.1:8765/"
Write-Host ""
Write-Host "RU: Ctrl+C останавливает backend."
Write-Host "EN: Ctrl+C stops the backend."
Write-Host ""

uv run python -m backend.app

if (-not $NoPause) {
    Read-Host "Press Enter / Нажми Enter"
}
