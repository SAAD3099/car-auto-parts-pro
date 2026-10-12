@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m unittest discover -s tests -v
goto done
:use_python
python -m unittest discover -s tests -v
:done
pause
