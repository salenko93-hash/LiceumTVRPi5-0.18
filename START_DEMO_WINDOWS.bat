@echo off
setlocal
cd /d "%~dp0"
if not exist "public\media-dashboard.html" (
  echo ERROR: public\media-dashboard.html was not found.
  pause
  exit /b 1
)
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY_CMD=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python 3 is required. Install it and try again.
    pause
    exit /b 1
  )
  set "PY_CMD=python"
)
echo Starting LyceumTV preview on http://127.0.0.1:8094/media-dashboard.html?demo=1
start "LyceumTV DEMO SERVER - keep open" cmd /k "cd /d ""%~dp0"" && %PY_CMD% -m http.server 8094 --bind 127.0.0.1 --directory public"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8094/media-dashboard.html?demo=1"
echo If page shows 404, check that the server window is running, then refresh.
endlocal
