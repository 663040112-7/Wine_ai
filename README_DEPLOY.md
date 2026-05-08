# Wine AI — Deployment Guide

## วิธีที่ 1: Cloudflare Tunnel (แนะนำ — ง่ายสุด ฟรี)

### ขั้นตอน
1. ติดตั้ง cloudflared:
```
winget install Cloudflare.cloudflared
```

2. ดับเบิลคลิก `tunnel.bat`
   - Server จะเริ่มต้นอัตโนมัติ
   - URL จะปรากฏ เช่น `https://random-name.trycloudflare.com`

3. แชร์ URL ให้ทีมงานดูได้เลย

### ข้อดี
- ฟรี ไม่ต้องสมัคร
- รันได้ทันที
- กล้องต่อตรงได้

### ข้อเสีย
- URL เปลี่ยนทุกครั้งที่ restart
- ต้องเปิด PC ตลอด

---

## วิธีที่ 2: Railway + PC Hybrid

### Architecture
```
PC ร้าน (local)          Railway (cloud)
├── main.py (detection)  ├── server.py (dashboard)
├── server.py (local)    └── รับข้อมูลจาก PC
└── cloud_pusher.py ──────→ /api/push ทุก 3 วิ
```

### ขั้นตอน Deploy Railway

1. สร้าง GitHub repo ใหม่ ชื่อ `wine-ai-dashboard`

2. Copy ไฟล์เหล่านี้ขึ้น GitHub:
```
server.py
templates/index.html
report.py
report_pdf.py
ai_insight.py
data_manager.py
zones.py
behavior_engine.py
alert.py
logger.py
tracker.py
dashboard.py
zones_config.json
Procfile
requirements.txt
runtime.txt
```

3. ไป railway.com → New Project → Deploy from GitHub

4. ตั้ง Environment Variables ใน Railway:
```
CLOUD_MODE    = 1
PUSH_SECRET   = (รหัสที่คุณตั้ง เช่น wine2026)
GEMINI_API_KEY = (optional)
```

5. Railway จะให้ URL เช่น `https://wine-ai.up.railway.app`

### ขั้นตอนรัน PC ร้าน

```bash
# Terminal 1 — Detection
python main.py rtsp://winecam:123456789@192.168.1.122/stream2

# Terminal 2 — Local server
python server.py

# Terminal 3 — Push ข้อมูลขึ้น Railway
python cloud_pusher.py --url https://wine-ai.up.railway.app --secret wine2026
```

### ข้อดี
- Dashboard ดูได้จากทุกที่ตลอด 24 ชั่วโมง
- URL คงที่ไม่เปลี่ยน
- ถ้า PC ดับ dashboard ยังเข้าได้ (แต่ข้อมูลไม่อัปเดต)

---

## วิธีที่ 3: Auto Start เมื่อเปิดเครื่อง

1. กด `Win + R` พิมพ์ `shell:startup`
2. Copy shortcut ของ `autostart.bat` ไปวางใน folder นั้น
3. ทุกครั้งที่เปิดเครื่อง Wine AI จะเริ่มอัตโนมัติ

---

## Troubleshooting

| ปัญหา | วิธีแก้ |
|---|---|
| cloudflared ไม่พบ | รัน: `winget install Cloudflare.cloudflared` |
| Railway build failed | ตรวจสอบ requirements.txt |
| Push failed | ตรวจสอบ PUSH_SECRET ตรงกันไหม |
| Stream ไม่ขึ้น | กล้องเชื่อม WiFi เดียวกันไหม |
