@echo off
cd /d "%~dp0"
if not exist "config\.env.local" (
  echo Missing config\.env.local. Create it from config\.env.example first.
  pause
  exit /b 1
)
YingMuShouWang.exe live --config "config\.env.local"
if errorlevel 1 pause
