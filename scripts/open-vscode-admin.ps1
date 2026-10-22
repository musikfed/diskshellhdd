param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# RU: Этот вариант повышает ВЕСЬ VS Code, включая расширения.
# EN: This elevates the ENTIRE VS Code process, including extensions.
# RU/EN: Используй только для доверенного workspace / Use only for a trusted workspace.

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$code = Get-Command code -ErrorAction Stop

Start-Process -FilePath $code.Source -Verb RunAs -ArgumentList @(
    "--reuse-window",
    $ProjectRoot
)
