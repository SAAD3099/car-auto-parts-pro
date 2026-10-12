@echo off
setlocal
cd /d "%~dp0"
title AutoParts Pro - Admin Password Recovery
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 maintenance.py recover
goto done
:use_python
python maintenance.py recover
:done
pause
