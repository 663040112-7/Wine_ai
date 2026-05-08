@echo off
echo ============================================
echo   Wine AI — Auto Start (24 hours)
echo ============================================

REM รอให้ Windows โหลดเสร็จ (ใช้ตอน startup)
timeout /t 10 /nobreak > nul

REM เริ่ม server
cd /d "D:\Work\WIne AI\wine_web"
call conda activate wine_ai
start "Wine AI" pythonw server.py

REM เริ่ม tunnel
timeout /t 5 /nobreak > nul
cloudflared tunnel --url http://localhost:5000 > tunnel_url.log 2>&1 &

echo Wine AI started!
