@echo off
rem Starts the Resolve MCP server. Creates a local virtual environment on first run.
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
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" resolve_mcp_server.py
goto :eof

:fail
echo Setup failed. You need Python 3.10 or newer on PATH.
exit /b 1
