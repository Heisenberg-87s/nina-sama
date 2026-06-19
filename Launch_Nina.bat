@echo off
echo =======================================
echo    Booting Nina-sama Server Stack...
echo =======================================

echo 1. Starting FastAPI Python Backend...
start "Nina Backend Server" cmd /k "cd /d %~dp0 && uvicorn nina_backend:app --host 0.0.0.0 --port 8000"

echo 2. Starting Electron React Frontend...
cd /d %~dp0\nina-ui
npm run start
