@echo off
setlocal
cd /d "%~dp0"
if exist ".runtime\dotnet\dotnet.exe" (
  set "DOTNET_ROOT=%~dp0.runtime\dotnet"
  set "DOTNET_ROOT_X64=%~dp0.runtime\dotnet"
  set "DOTNET_MULTILEVEL_LOOKUP=0"
  set "PATH=%~dp0.runtime\dotnet;%PATH%"
)
if exist "OFFLINE_RELEASE.json" (
  if not exist ".runtime\python313\tools\python.exe" (
    echo Offline bundle is incomplete. Extract the complete ZIP again.
    goto :failed
  )
  ".runtime\python313\tools\python.exe" scripts\offline_bootstrap.py
  if errorlevel 1 goto :failed
) else (
  if not exist ".venv\Scripts\python.exe" (
    echo Run install.cmd once, or use uv sync for development.
    goto :failed
  )
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Launch failed. Rerun install.cmd to repair the environment.
pause
exit /b 1
