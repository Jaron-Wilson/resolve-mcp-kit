@echo off
rem Starts the Resolve MCP server. Creates a virtual environment and installs what it needs on first run.
rem   set RESOLVE_MCP_SKIP_VIDEO=1   skip the site_video packages and the Chromium download (Resolve MCP tools only)
rem   set RESOLVE_MCP_REINSTALL=1    install the requirements again (after updating this folder)
rem Edit the settings below, or set the same variables in your environment first.
setlocal
cd /d "%~dp0"

if "%RESOLVE_MCP_TRANSPORT%"=="" set RESOLVE_MCP_TRANSPORT=sse
if "%RESOLVE_MCP_HOST%"=="" set RESOLVE_MCP_HOST=127.0.0.1
if "%RESOLVE_MCP_PORT%"=="" set RESOLVE_MCP_PORT=8930
rem Set to 1 to let the agent import media, build timelines and render.
if "%RESOLVE_MCP_ALLOW_WRITE%"=="" set RESOLVE_MCP_ALLOW_WRITE=1
rem Optional bearer token. Strongly recommended if RESOLVE_MCP_HOST is not 127.0.0.1.
rem set RESOLVE_MCP_TOKEN=pick-a-long-random-string

if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment in .venv ...
  py -3 -m venv .venv || python -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))" || goto :oldpython

if not exist ".venv\.deps-ok" goto :install
if not "%RESOLVE_MCP_REINSTALL%"=="" goto :install
goto :run

:install
echo Installing requirements ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
if "%RESOLVE_MCP_SKIP_VIDEO%"=="" (
  ".venv\Scripts\python.exe" -m pip install -r requirements-video.txt || goto :fail
  echo Downloading Chromium for site_video, about 150 MB, once ...
  ".venv\Scripts\python.exe" -m playwright install chromium || goto :fail
)
echo ok> ".venv\.deps-ok"

:run
".venv\Scripts\python.exe" resolve_mcp_server.py
goto :eof

:oldpython
echo Python 3.10 or newer is needed. Delete the .venv folder, install Python 3.12 from python.org, and run this again.
exit /b 1

:fail
echo Setup failed. You need Python 3.10 or newer on PATH, and internet access for pip.
exit /b 1
