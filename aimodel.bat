@echo off
setlocal enableextensions
cd /d "%~dp0"

REM ============================================================
REM  aimodel.bat - switch the AI gateway model for Claude Code
REM  NOTE: keep this file ASCII-only with CRLF line endings.
REM
REM  Usage:
REM    aimodel.bat list                 show every available model
REM    aimodel.bat cn:glm-5.3           set ONE model into all slots
REM    aimodel.bat --opus cn:auto --sonnet cn:balanced-model --haiku cn:fast-model
REM ============================================================

if "%~1"=="" (
  echo Usage:
  echo   aimodel.bat list                  show every available model
  echo   aimodel.bat cn:glm-5.3            set ONE model into all slots
  echo   aimodel.bat --opus X --sonnet Y --haiku Z
  echo Examples:
  echo   aimodel.bat list
  echo   aimodel.bat cn:auto
  echo   aimodel.bat cn:deepseek-v4-pro
  exit /b 0
)

if exist "backend\.venv\Scripts\python.exe" (
  backend\.venv\Scripts\python.exe ".claude\aimodel.py" %*
  goto end
)
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe ".claude\aimodel.py" %*
  goto end
)
python ".claude\aimodel.py" %*

:end
endlocal
