@echo off
setlocal
rem Setup uses direct connections; these settings end with this installer.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "FTP_PROXY="
set "PIP_PROXY="
set "NO_PROXY=*"
set "PIP_CONFIG_FILE=nul"
cd /d "%~dp0"
chcp 65001 >nul
if not exist "local" mkdir "local"
if exist "OFFLINE_RELEASE.json" (
  if not exist ".runtime\python313\tools\python.exe" goto :missing_bundle
  ".runtime\python313\tools\python.exe" scripts\offline_bootstrap.py --repair
  if errorlevel 1 goto :failed
  goto :success
)
rem Interpreter priority: bundled local runtime, py -3.13, PATH Python, pinned fetch.
set "EMG_SETUP_PYTHON="
if exist ".runtime\python313\tools\python.exe" (
  ".runtime\python313\tools\python.exe" -c "import sys,struct,platform; assert sys.version_info[:2]==(3,13) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64')" >nul 2>&1
  if not errorlevel 1 set "EMG_SETUP_PYTHON=%CD%\.runtime\python313\tools\python.exe"
)
if defined EMG_SETUP_PYTHON goto :prepare
chcp 65001 >nul
py -3.13 -c "import sys,struct,platform; assert sys.version_info[:2]==(3,13) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64')" >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3.13 -c "import sys;print(sys.executable)"') do set "EMG_SETUP_PYTHON=%%P"
)
if defined EMG_SETUP_PYTHON goto :prepare
chcp 65001 >nul
python.exe -c "import sys,struct,platform; assert sys.version_info[:2]==(3,13) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64')" >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('python.exe -c "import sys;print(sys.executable)"') do set "EMG_SETUP_PYTHON=%%P"
)
if defined EMG_SETUP_PYTHON goto :prepare
chcp 65001 >nul
call scripts\fetch_runtime.cmd
if errorlevel 1 goto :failed
set "EMG_SETUP_PYTHON=%CD%\.runtime\python313\tools\python.exe"
:prepare
chcp 65001 >nul
"%EMG_SETUP_PYTHON%" scripts\bootstrap.py
if errorlevel 1 goto :failed
:success
echo Setup complete. Double-click start.cmd to run.
if /i not "%~1"=="--no-pause" pause
exit /b 0
:missing_bundle
echo Bundled Python is missing. Extract the complete offline ZIP again.
:failed
echo Setup failed. See the message above and local\setup.log. Rerun install.cmd to retry.
if /i not "%~1"=="--no-pause" pause
exit /b 1
