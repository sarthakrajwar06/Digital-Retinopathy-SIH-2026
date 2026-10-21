@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 18.17 or newer, then run this script again.
  pause
  exit /b 1
)

if not defined PORT set PORT=3000
if not exist "node_modules\express" (
  echo Installing local APL auction dependencies. Internet access is needed for this first install.
  call npm install
  if errorlevel 1 (
    echo Dependency installation failed. Run npm install from this folder and try again.
    pause
    exit /b 1
  )
)

echo Starting Auction Premier League on port %PORT%...
echo Keep this window open during the event. Press Ctrl+C here to stop safely.
node server.js
if errorlevel 1 (
  echo The auction server stopped with an error. See the message above.
  pause
)
endlocal
