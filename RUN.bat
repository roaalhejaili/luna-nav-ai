@echo off
cd /d "%~dp0"
if not exist "%~dp0scripts\run_all.ps1" (
  echo.
  echo  LUNA NAV AI cannot start from inside the zip file.
  echo  Right-click LUNA_NAV_AI_FINAL.zip, choose "Extract All...", open the extracted
  echo  LUNA_NAV_AI_FINAL folder, then double-click RUN.bat there.
  echo.
  pause
  exit /b 1
)
if not exist "%~dp0.venv\Scripts\python.exe" goto setup
if not exist "%~dp0original_modules\person3\moon_navigation\node_modules" goto setup
goto run
:setup
echo First run: installing everything (one time, about 3-5 minutes, needs internet)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_all.ps1"
if errorlevel 1 (
  echo.
  echo  Setup failed. Read the red message above.
  pause
  exit /b 1
)
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_all.ps1"
pause
