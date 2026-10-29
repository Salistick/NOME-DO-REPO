@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_scripts\build_windows.ps1" %*
exit /b %ERRORLEVEL%
