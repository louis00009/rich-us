@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM  QuantDesk for IBKR - one-click launcher
REM  NOTE: keep this file ASCII-only with CRLF line endings.
REM  cmd.exe parses .bat with the OEM codepage (GBK on zh-CN);
REM  UTF-8 Chinese text gets mangled into broken commands.
REM ============================================================

set PORT=8787

echo ====================================================================
echo   QuantDesk for IBKR - launcher
echo ====================================================================

REM ---- [0/4] free port %PORT% from stale instances ----
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
  echo [0/4] Port %PORT% is used by PID %%P - stopping old instance...
  taskkill /PID %%P /F >nul 2>&1
)

REM ---- [1/4][2/4] python venv + backend deps ----
if exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] Python venv found
  echo [2/4] Backend dependencies OK
  goto front
)
echo [1/4] Creating Python virtual environment...
python -m venv backend\.venv
if errorlevel 1 (
  echo   X venv creation failed. Please install Python 3.11+ first.
  pause
  exit /b 1
)
echo [2/4] Installing backend dependencies (1-3 min)...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
if errorlevel 1 (
  echo   X backend dependency installation failed.
  pause
  exit /b 1
)

:front
REM ---- [3/4] frontend build ----
if exist "frontend\dist\index.html" (
  echo [3/4] Frontend build found
  goto run
)
echo [3/4] Installing and building frontend (1-2 min)...
pushd frontend
if not exist "node_modules" (
  call npm install --no-fund --no-audit
)
call npm run build
popd

:run
echo [4/4] Starting server on http://127.0.0.1:%PORT%/
echo.
cd backend
.venv\Scripts\python.exe run.py

endlocal
pause
