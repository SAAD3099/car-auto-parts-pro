@echo off
setlocal
cd /d "%~dp0"
title AutoParts Pro - Restore Backup
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 maintenance.py restore
goto done
:use_python
python maintenance.py restore
:done
pause
