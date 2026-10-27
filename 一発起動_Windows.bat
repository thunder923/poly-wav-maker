@echo off
rem Poly WAV Maker - Windows launcher
rem Usage: drag and drop take folders (multiple OK) onto this .bat,
rem        or double-click it and pick a folder in the dialog.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python 3 was not found.
  echo Install Python 3 from https://www.python.org/downloads/ - check "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

if "%~1"=="" (
  echo No folder was dropped. Opening folder picker...
  for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = 'Select a take folder (or a parent folder with many takes)'; if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.SelectedPath }"`) do set "TARGET=%%I"
  if not defined TARGET ( echo Cancelled. & pause & exit /b 0 )
  %PY% poly_wav.py "%TARGET%"
) else (
  %PY% poly_wav.py %*
)

echo.
echo Done. You can close this window.
pause
