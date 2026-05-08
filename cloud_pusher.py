# =============================================================================
# cloud_pusher.py — ส่ง HUD state และ alerts ไปยัง Railway server
# รันบน PC ร้านพร้อมกับ server.py
#
# Usage:
#   python cloud_pusher.py --url https://your-app.up.railway.app
#   python cloud_pusher.py --url https://your-app.up.railway.app --secret mypassword
# =============================================================================
import time
import json
import argparse
import urllib.request
import urllib.error
import os

def push_to_cloud(cloud_url: str, secret: str = "",
                  local_url: str = "http://localhost:5000"):
    """ดึงข้อมูลจาก local server แล้วส่งขึ้น cloud"""
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Push-Secret"] = secret

    # ดึง HUD จาก local
    try:
        with urllib.request.urlopen(f"{local_url}/api/hud", timeout=3) as r:
            hud = json.loads(r.read())
    except Exception as e:
        print(f"[Pusher] Cannot reach local server: {e}")
        return False

    # ดึง alerts จาก local
    try:
        with urllib.request.urlopen(f"{local_url}/api/alerts", timeout=3) as r:
            alert_list = json.loads(r.read())
    except Exception:
        alert_list = []

    # ส่งขึ้น cloud
    payload = json.dumps({
        "hud":    hud,
        "alerts": alert_list[-10:],  # ส่งแค่ 10 รายการล่าสุด
    }).encode()

    try:
        req = urllib.request.Request(
            f"{cloud_url}/api/push",
            data=payload, headers=headers
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            result = json.loads(r.read())
            return result.get("ok", False)
    except urllib.error.HTTPError as e:
        print(f"[Pusher] HTTP {e.code}: {e.read().decode()[:100]}")
        return False
    except Exception as e:
        print(f"[Pusher] Push failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Wine AI Cloud Pusher")
    parser.add_argument("--url",      required=True,
                        help="Railway URL เช่น https://xxx.up.railway.app")
    parser.add_argument("--secret",   default=os.environ.get("PUSH_SECRET",""),
                        help="Secret key (ถ้าตั้งไว้ใน Railway)")
    parser.add_argument("--local",    default="http://localhost:5000",
                        help="Local server URL")
    parser.add_argument("--interval", default=3, type=int,
                        help="ส่งทุกกี่วินาที (default: 3)")
    args = parser.parse_args()

    print(f"[Pusher] Starting — pushing to {args.url} every {args.interval}s")
    print(f"[Pusher] Press Ctrl+C to stop\n")

    while True:
        ok = push_to_cloud(args.url, args.secret, args.local)
        status = "✅" if ok else "❌"
        print(f"\r[Pusher] {status} {time.strftime('%H:%M:%S')} → {args.url}", end="")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
