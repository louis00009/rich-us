@echo off
REM Stop QuantDesk server listening on port 8787
set PORT=8787
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
  echo Stopping QuantDesk PID %%P ...
  taskkill /PID %%P /F >nul 2>&1
)
echo Done.
