@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_boss_gacha.ps1" %*
exit /b %ERRORLEVEL%
