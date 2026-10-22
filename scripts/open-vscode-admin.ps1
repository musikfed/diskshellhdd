param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# RU: Этот вариант повышает ВЕСЬ VS Code, включая расширения.
# EN: This elevates the ENTIRE VS Code process, including extensions.
# RU/EN: Используй только для доверенного workspace / Use only for a trusted workspace.

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$code = Get-Command code -ErrorAction Stop
$source = $code.Source

if ([IO.Path]::GetExtension($source) -ieq ".cmd") {
    $command = '"' + $source + '" --reuse-window "' + $ProjectRoot + '"'
    Start-Process -FilePath $env:ComSpec -Verb RunAs -ArgumentList @(
        "/d",
        "/c",
        $command
    )
} else {
    Start-Process -FilePath $source -Verb RunAs -ArgumentList @(
        "--reuse-window",
        ('"' + $ProjectRoot + '"')
    )
}
