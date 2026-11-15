@echo off
setlocal
cd /d "%~dp0"
set "DOTNET_ROOT=%CD%\.runtime\dotnet"
set "DOTNET_ROOT_X64=%DOTNET_ROOT%"
set "DOTNET_MULTILEVEL_LOOKUP=0"
set "PATH=%DOTNET_ROOT%;%PATH%"
if exist "OFFLINE_RELEASE.json" (
  ".runtime\python313\tools\python.exe" scripts\windows_acceptance.py --workflow offline %*
  if errorlevel 1 goto :failed
) else (
  rem Source acceptance deliberately starts with unusable proxy settings.
  set "HTTP_PROXY=http://127.0.0.1:9"
  set "HTTPS_PROXY=http://127.0.0.1:9"
  set "ALL_PROXY=http://127.0.0.1:9"
  set "PIP_PROXY=http://127.0.0.1:9"
  call install.cmd --no-pause
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" scripts\windows_acceptance.py --workflow source %*
  if errorlevel 1 goto :failed
)
pause
exit /b 0
:failed
echo Windows acceptance failed. See local\windows-acceptance.json and local\setup.log.
pause
exit /b 1
