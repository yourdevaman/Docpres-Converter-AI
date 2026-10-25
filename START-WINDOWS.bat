@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Docpres Converter AI - Local Launcher
echo ==========================================

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python environment...
  py -m venv .venv
  if errorlevel 1 (
    echo ERROR: Python was not found. Install Python 3.11+ and try again.
    pause
    exit /b 1
  )
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example.
  echo Add your NEW Gemini API key to .env, save it, then run this file again.
  notepad .env
  pause
  exit /b 0
)

findstr /i /c:"GEMINI_API_KEY=replace_with_" ".env" >nul
if not errorlevel 1 (
  echo ERROR: .env still contains the placeholder key.
  echo Replace it with your NEW Gemini API key, save, then run this file again.
  notepad .env
  pause
  exit /b 1
)

echo Installing/checking dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Dependencies could not be installed. Check your internet connection.
  pause
  exit /b 1
)

echo Starting server. Keep this window open while using the site.
".venv\Scripts\python.exe" app.py
pause
