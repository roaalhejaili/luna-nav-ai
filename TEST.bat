@echo off
cd /d "%~dp0"
if not exist "%~dp0scripts\test_all.ps1" (
  echo.
  echo  LUNA NAV AI cannot start from inside the zip file.
  echo  Right-click LUNA_NAV_AI_FINAL.zip, choose "Extract All...", open the extracted
  echo  LUNA_NAV_AI_FINAL folder, then double-click TEST.bat there.
  echo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test_all.ps1"
pause
