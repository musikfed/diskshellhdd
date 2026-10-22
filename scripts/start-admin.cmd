@echo off
setlocal
REM RU: Удобный launcher для двойного клика / cmd.exe.
REM EN: Convenience launcher for double-click / cmd.exe.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-admin.ps1"
endlocal
