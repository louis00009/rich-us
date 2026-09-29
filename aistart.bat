@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM  QuantDesk for IBKR - AI full-stack launcher (aistart.bat)
REM  NOTE: keep this file ASCII-only with CRLF line endings.
REM
REM  Ensures BOTH projects are fully running, then starts Claude
REM  Code wired to the local AI gateway:
REM
REM    [1/4] workbuddy2api upstream   127.0.0.1:16688  (scheduled task WorkBuddy2API)
REM    [2/4] workbuddy-manager panel  127.0.0.1:16689  (scheduled task WorkBuddyManager)
REM          -> checks the account pool is not empty
REM    [3/4] QuantDesk platform       127.0.0.1:8787   (delegates to start.bat in its own window)
REM    [4/4] claude (Claude Code) in this window, env from .claude\settings.local.json
REM
REM  The gateway key + model mapping live in .claude\settings.local.json
REM  (git-ignored). Switch models with aimodel.bat.
REM ============================================================

set WBUPSTREAM=16688
set WBPANEL=16689
set QDPORT=8787

echo ====================================================================
echo   QuantDesk AI stack launcher
echo ====================================================================

REM ---- [1/4] workbuddy2api upstream ------------------------------------
curl.exe -s -o nul --max-time 3 http://127.0.0.1:%WBUPSTREAM%/healthz >nul 2>&1
if not errorlevel 1 (
  echo [1/4] AI upstream already running on %WBUPSTREAM%
  goto panel
)
echo [1/4] Starting AI upstream (scheduled task WorkBuddy2API)...
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'WorkBuddy2API'" >nul 2>&1
set /a TRIES=0
:wait_upstream
curl.exe -s -o nul --max-time 2 http://127.0.0.1:%WBUPSTREAM%/healthz >nul 2>&1
if not errorlevel 1 goto upstream_ok
set /a TRIES+=1
if %TRIES% GEQ 30 goto upstream_fail
timeout /t 1 /nobreak >nul
goto wait_upstream
:upstream_ok
echo [1/4] AI upstream is up on %WBUPSTREAM%
goto panel
:upstream_fail
echo   X AI upstream did not come up in 30s.
echo     Check: C:\Users\Louis\workbuddy-manager\upstream\data\server.err.log
echo     Continuing anyway - the panel may still start...

REM ---- [2/4] workbuddy-manager panel -----------------------------------
:panel
curl.exe -s -o nul --max-time 3 http://127.0.0.1:%WBPANEL%/ >nul 2>&1
if not errorlevel 1 (
  echo [2/4] AI panel already running on %WBPANEL%
  goto poolcheck
)
echo [2/4] Starting AI panel (scheduled task WorkBuddyManager)...
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'WorkBuddyManager'" >nul 2>&1
set /a TRIES=0
:wait_panel
curl.exe -s -o nul --max-time 2 http://127.0.0.1:%WBPANEL%/ >nul 2>&1
if not errorlevel 1 goto panel_ok
set /a TRIES+=1
if %TRIES% GEQ 40 goto panel_fail
timeout /t 1 /nobreak >nul
goto wait_panel
:panel_ok
echo [2/4] AI panel is up on %WBPANEL%
goto poolcheck
:panel_fail
echo   X AI panel did not come up in 40s.
echo     Check: C:\Users\Louis\workbuddy-manager\data\launcher.err.log
echo     Claude Code will not work without it - fix and rerun.
pause
exit /b 1

REM ---- pool sanity check ------------------------------------------------
:poolcheck
powershell -NoProfile -Command "$h = Invoke-RestMethod -TimeoutSec 5 http://127.0.0.1:%WBUPSTREAM%/healthz; if ($h.healthy -gt 0) { Write-Output ('POOL-OK ' + $h.healthy) } else { Write-Output 'POOL-EMPTY' }" > "%TEMP%\wbm_pool.txt" 2>nul
findstr /C:"POOL-EMPTY" "%TEMP%\wbm_pool.txt" >nul 2>&1
if errorlevel 1 (
  for /f "tokens=2" %%N in (%TEMP%\wbm_pool.txt) do echo        Account pool: %%N healthy account(s)
  del "%TEMP%\wbm_pool.txt" >nul 2>&1
  goto qd
)
echo        WARNING: account pool is EMPTY. Scan a QR code first:
echo        open http://127.0.0.1:%WBPANEL% - Accounts - Add Account
echo        Claude Code will start, but every request will fail until then.
del "%TEMP%\wbm_pool.txt" >nul 2>&1

REM ---- [3/4] QuantDesk platform -----------------------------------------
REM Preferred: scheduled task QuantDeskServer (survives window close,
REM same pattern as WorkBuddy2API / WorkBuddyManager). Fallback: start.bat
REM in a separate window (visible console, first-run dependency install).
:qd
netstat -ano 2>nul | findstr ":%QDPORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [3/4] QuantDesk already running on %QDPORT%
  goto claude
)
powershell -NoProfile -Command "if (Get-ScheduledTask -TaskName 'QuantDeskServer' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [3/4] Starting QuantDesk in a separate window (start.bat)...
  start "QuantDesk" cmd /c "%~dp0start.bat"
  goto wait_qd
)
echo [3/4] Starting QuantDesk (scheduled task QuantDeskServer)...
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'QuantDeskServer'" >nul 2>&1
:wait_qd
netstat -ano 2>nul | findstr ":%QDPORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto qd_ok
set /a TRIES+=1
if %TRIES% GEQ 180 goto qd_fail
timeout /t 2 /nobreak >nul
goto wait_qd
:qd_ok
echo [3/4] QuantDesk is up on %QDPORT%
goto claude
:qd_fail
echo   X QuantDesk did not listen on %QDPORT% within 6 min.
echo     First run may need to install dependencies - check the QuantDesk window.
echo     Continuing - AI chat works even while QuantDesk is still building.

REM ---- [4/4] claude ------------------------------------------------------
:claude
echo [4/4] Starting Claude Code (gateway config from .claude\settings.local.json)...
where claude >nul 2>&1
if errorlevel 1 (
  echo   X claude CLI not found in PATH.
  echo     Install: npm install -g @anthropic-ai/claude-code
  pause
  exit /b 1
)
echo.
echo   Tips:
echo     - switch model in-session :  /model   (opus=cn:auto sonnet=cn:balanced-model haiku=cn:fast-model)
echo     - switch model on disk    :  aimodel.bat list ^|^| aimodel.bat cn:glm-5.3
echo     - panel (keys/logs/pool)  :  http://127.0.0.1:%WBPANEL%
echo.
claude

endlocal
