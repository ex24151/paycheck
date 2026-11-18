@echo off
title PayCheck
cd /d "%~dp0"

rem --- Find Python ---
set PY=
where py >nul 2>nul && set PY=py
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo.
  echo  Python is not installed.
  echo  1. Go to https://www.python.org/downloads/ and install it.
  echo  2. IMPORTANT: tick "Add python.exe to PATH" during install.
  echo  3. Then double-click start.bat again.
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

rem --- First run: set everything up ---
if not exist ".venv\Scripts\python.exe" (
  echo Setting up PayCheck for the first time. This takes 1-2 minutes...
  %PY% -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :error
)
if not exist "paycheck.db" (
  echo Loading demo invoices...
  ".venv\Scripts\python.exe" -m app.seed || goto :error
)

echo.
echo  ===============================================
echo   PayCheck is running at  http://localhost:8000
echo   Keep this window open. Close it to stop.
echo  ===============================================
echo.
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
pause
exit /b 0

:error
echo.
echo  Something went wrong. Take a screenshot of this window and send it to Claude.
pause
exit /b 1
