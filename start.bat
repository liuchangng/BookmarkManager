@echo off
title Bookmark Manager - Launcher
cd /d "%~dp0"

rem ---- Read web port from config.yaml (web section, default 8989) ----
rem Note: proxy section also has a port (7890); regex anchors to "web:"
set "PORT=8989"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "try { $m = [regex]::Match((Get-Content 'config.yaml' -Raw), 'web:[\s\S]*?port:\s*(\d+)'); $m.Groups[1].Value } catch { '' }"`) do set "PORT=%%p"
if "%PORT%"=="" set "PORT=8989"

set "URL=http://127.0.0.1:%PORT%"
echo.
echo  ==========================================
echo    Bookmark Manager - One-click launcher
echo  ==========================================
echo.

rem ---- Already running? Just open the browser ----
for /f %%c in ('curl.exe -s -o nul -w "%%{http_code}" --max-time 2 "%URL%/" 2^>nul') do set "CODE=%%c"
if "%CODE%"=="200" (
    echo  [OK] Service already running: %URL%
    start "" "%URL%"
    goto :end
)

rem ---- Check uv ----
where uv >nul 2>&1
if errorlevel 1 (
    echo  [X] uv not found. Install it first: https://docs.astral.sh/uv/
    echo      Install command: pip install uv
    goto :end
)

rem ---- Sync dependencies ----
echo  [..] Syncing dependencies (uv sync) ...
uv sync
if errorlevel 1 (
    echo  [X] uv sync failed. Check your network and retry.
    goto :end
)
echo.

rem ---- Start the app ----
rem webapp.py opens the browser automatically (config: web.auto_open_browser)
echo  [OK] Starting service: %URL%
uv run python webapp.py

:end
echo.
pause
