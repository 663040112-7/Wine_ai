@echo off
echo ============================================
echo   Wine AI — Cloudflare Tunnel Launcher
echo ============================================
echo.

REM ตรวจสอบว่ามี cloudflared ไหม
where cloudflared >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] cloudflared ไม่พบ กำลังติดตั้ง...
    winget install Cloudflare.cloudflared
    echo.
)

echo [1] เริ่ม Wine AI Server...
start "Wine AI Server" cmd /k "cd /d %~dp0 && conda activate wine_ai && python server.py"

echo [2] รอ 5 วินาทีให้ server เริ่มต้น...
timeout /t 5 /nobreak > nul

echo [3] เปิด Cloudflare Tunnel...
echo.
echo ============================================
echo   URL ของคุณจะปรากฏด้านล่าง
echo   แชร์ URL นี้ให้ทีมงานดูได้เลย
echo ============================================
echo.
cloudflared tunnel --url http://localhost:5000

pause
