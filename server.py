# =============================================================================
# server.py — Wine AI Web Server (Simple & Reliable)
# Uses Flask + threading, MJPEG stream via HTTP
# Install: pip install flask
# Run:     python server.py
# =============================================================================
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

# Cloud mode — ถ้ารันบน Railway หรือไม่มี camera
# ตั้ง CLOUD_MODE=1 ใน Railway environment variables
CLOUD_MODE = os.environ.get("CLOUD_MODE", "0") == "1"

import sys
import cv2
import time
import queue
import threading
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, Response, jsonify, request, render_template_string

sys.path.insert(0, os.path.dirname(__file__))

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH      = "behavior_log.db"
ZONES_CONFIG = "zones_config.json"
MODEL_PATH   = "yolov8n.pt"
TZ_OFFSET    = 7

# ── State ──────────────────────────────────────────────────────────────────────
state = {
    "running":    False,
    "rtsp_url":   "rtsp://winecam:123456789@192.168.1.122/stream2",
    "anonymize":  False,
    "conf":       0.25,
    "dwell_interested":      25,
    "dwell_loitering":       90,
    "dwell_checkout_min":    5,
    "dwell_seating_waiting": 180,
    "gemini_api_key":  "",   # Google Gemini API key (free)
    "claude_api_key":  "",   # Anthropic Claude API key (paid)
}
hud    = {"cust": 0, "seller": 0, "alert": 0}
alerts = []  # list of alert dicts

frame_q      = queue.Queue(maxsize=2)   # display frame (annotated)
raw_frame_q  = queue.Queue(maxsize=2)   # raw frame for stream
stop_evt = threading.Event()
eng_thread = None
stream_thread = None

# ── Flask ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── MJPEG stream ──────────────────────────────────────────────────────────────
def gen():
    import numpy as np
    blank = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(blank, "Waiting for camera...", (80, 180),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (80, 80, 80), 2)
    _, blank_jpg = cv2.imencode(".jpg", blank)

    while True:
        # ลอง display frame ก่อน ถ้าไม่มีใช้ blank
        try:
            frame = frame_q.get_nowait()
            _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
            data = jpg.tobytes()
        except queue.Empty:
            data = blank_jpg.tobytes()
            time.sleep(0.033)   # ~30fps

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n")

@app.route("/stream")
def stream():
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ── API ───────────────────────────────────────────────────────────────────────
@app.route("/api/hud")
def api_hud():
    return jsonify({**hud, "running": state["running"]})

@app.route("/api/alerts")
def api_alerts():
    return jsonify(alerts[-20:])

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.json or {}
        for k, v in data.items():
            if k in state:
                state[k] = v
        return jsonify({"ok": True})
    return jsonify({k: v for k, v in state.items() if k != "running"})

@app.route("/api/start", methods=["POST"])
def api_start():
    global eng_thread
    if CLOUD_MODE:
        return jsonify({"ok": False, "msg": "Cloud mode — detection runs on local PC only"})
    if state["running"]:
        return jsonify({"ok": False, "msg": "already running"})
    stop_evt.clear()
    eng_thread = threading.Thread(target=engine_loop, daemon=True)
    eng_thread.start()
    state["running"] = True
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_evt.set()
    state["running"] = False
    hud.update({"cust": 0, "seller": 0, "alert": 0})
    return jsonify({"ok": True})

@app.route("/api/stats")
def api_stats():
    if not Path(DB_PATH).exists():
        return jsonify({"total": 0, "interested": 0, "purchasing": 0, "top_zone": "N/A"})
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    def q(sql, p=()):
        return conn.execute(sql, p).fetchall()
    date_f = f"date(datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours'))=?"
    # นับจาก is_new_visit=1 เพื่อกัน duplicate จาก ID switching
    total  = q(f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 AND {date_f}", (today,))[0][0]
    if total == 0:  # fallback สำหรับ DB เก่าที่ไม่มี column
        total = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE {date_f}", (today,))[0][0]
    inter  = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='interested' AND {date_f}", (today,))[0][0]
    purch  = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='purchasing' AND {date_f}", (today,))[0][0]
    tz     = q(f"SELECT zone,COUNT(*) n FROM events WHERE zone!='floor' AND {date_f} GROUP BY zone ORDER BY n DESC LIMIT 1", (today,))
    conn.close()
    return jsonify({"total": total, "interested": inter, "purchasing": purch,
                    "top_zone": tz[0][0] if tz else "N/A", "date": today})

@app.route("/api/hourly")
def api_hourly():
    if not Path(DB_PATH).exists():
        return jsonify({"labels": [], "datasets": []})
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(f"""
        SELECT strftime('%H',datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours')) hr,
               behavior, COUNT(*) n
        FROM events
        WHERE date(datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours'))=?
        GROUP BY hr, behavior ORDER BY hr
    """, (today,)).fetchall()
    conn.close()

    hours = [f"{h:02d}:00" for h in range(24)]
    behs  = ["wine_browsing","interested","loitering","purchasing","processing","seated","waiting"]
    cols  = ["#B8860B","#E65100","#CC0000","#228B22","#008B8B","#D2691E","#8B0000"]
    datasets = []
    for b, c in zip(behs, cols):
        bmap = {r[0]: r[2] for r in rows if r[1] == b}
        datasets.append({"label": b.replace("_"," ").title(),
                         "data": [bmap.get(f"{h:02d}", 0) for h in range(24)],
                         "backgroundColor": c, "borderRadius": 4})
    return jsonify({"labels": hours, "datasets": datasets})

@app.route("/api/zones")
def api_zones():
    if not Path(DB_PATH).exists():
        return jsonify([])
    conn = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute(f"""
        SELECT zone, COUNT(*) n FROM events
        WHERE zone!='floor'
          AND date(datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours'))=?
        GROUP BY zone ORDER BY n DESC LIMIT 8
    """, (today,)).fetchall()
    conn.close()
    return jsonify([{"zone": r[0], "count": r[1]} for r in rows])


@app.route("/api/frame")
def api_frame():
    """ดึง frame ปัจจุบันจากกล้องเป็น base64 สำหรับ Zone Editor"""
    import base64, numpy as np
    try:
        frame = frame_q.get(timeout=1)
    except queue.Empty:
        # ถ้าไม่มี frame ให้ต่อกล้องชั่วคราว
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(state["rtsp_url"], cv2.CAP_FFMPEG)
        for _ in range(5): cap.read()
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return jsonify({"ok": False, "msg": "no frame"})

    # ส่ง frame ขนาดจริงเพื่อให้ Zone Editor วาดตรง coordinate กับ zones_config
    h, w = frame.shape[:2]
    # scale ให้กว้างสุด 1280 เพื่อลด transfer size แต่ยังคง aspect ratio
    if w > 1280:
        scale = 1280 / w
        frame = cv2.resize(frame, (1280, int(h * scale)))
        h, w = frame.shape[:2]
    _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    b64 = base64.b64encode(jpg.tobytes()).decode()
    return jsonify({"ok": True, "image": b64, "width": w, "height": h})

@app.route("/api/zones/load")
def api_zones_load():
    """โหลด zones_config.json"""
    if not Path(ZONES_CONFIG).exists():
        return jsonify({"cam_0": {}})
    with open(ZONES_CONFIG) as f:
        return jsonify(json.load(f))

@app.route("/api/zones/save", methods=["POST"])
def api_zones_save():
    """บันทึก zones_config.json"""
    data = request.json
    if not data:
        return jsonify({"ok": False, "msg": "no data"})
    with open(ZONES_CONFIG, "w") as f:
        json.dump(data, f, indent=2)
    # reload zone_manager ถ้ากำลังรันอยู่
    return jsonify({"ok": True, "saved": ZONES_CONFIG})

@app.route("/api/report/html")
def api_report_html():
    """Generate HTML report"""
    if not Path(DB_PATH).exists():
        return jsonify({"ok": False, "msg": "no database"})
    date_arg = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    try:
        from report import build_report
        html = build_report(DB_PATH, date_arg)
        return Response(html, mimetype="text/html",
                       headers={"Content-Disposition": f"attachment; filename=report_{date_arg}.html"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/report/pdf")
def api_report_pdf():
    """Generate PDF report using ReportLab"""
    if not Path(DB_PATH).exists():
        return jsonify({"ok": False, "msg": "no database"})
    date_arg = request.args.get("date", None)
    import tempfile
    try:
        from report_pdf import build_pdf
        tmp = tempfile.mktemp(suffix=".pdf")
        build_pdf(DB_PATH, date_arg, tmp)
        with open(tmp, "rb") as f:
            data = f.read()
        os.remove(tmp)
        fname = f"report_{date_arg or 'all'}.pdf"
        return Response(data, mimetype="application/pdf",
                       headers={"Content-Disposition": f"attachment; filename={fname}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/jpeg")
def api_jpeg():
    """Single JPEG frame — polled by frontend every ~100ms. No flicker."""
    import numpy as np
    try:
        frame = frame_q.get_nowait()
    except queue.Empty:
        # return last known frame or black
        frame = getattr(api_jpeg, '_last', None)
        if frame is None:
            frame = np.zeros((540, 960, 3), dtype=np.uint8)

    api_jpeg._last = frame
    _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(jpg.tobytes(), mimetype="image/jpeg",
                   headers={"Cache-Control": "no-cache, no-store",
                            "Pragma": "no-cache"})


@app.route("/api/insight")
def api_insight():
    """AI insight — ใช้ Gemini (ฟรี) หรือ Claude หรือ rule-based อัตโนมัติ"""
    if not Path(DB_PATH).exists():
        return jsonify({"ok": False, "msg": "no database"})
    date_arg = request.args.get("date", None)
    # ลำดับ: state > env variable
    gemini_key = state.get("gemini_api_key","") or os.environ.get("GEMINI_API_KEY","")
    claude_key = state.get("claude_api_key","") or os.environ.get("ANTHROPIC_API_KEY","")
    api_key    = gemini_key or claude_key
    try:
        from ai_insight import get_ai_insight, insight_to_html
        result = get_ai_insight(DB_PATH, date_arg, api_key=api_key)
        return jsonify({
            "ok":     result["ok"],
            "html":   insight_to_html(result.get("insight") or result.get("fallback","")),
            "source": result.get("source","Automated Analysis"),
            "data":   result.get("data", {}),
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/push", methods=["POST"])
def api_push():
    """
    PC local ส่ง HUD state และ alerts มาอัปเดต
    ใช้ PUSH_SECRET เป็น simple auth
    """
    secret = os.environ.get("PUSH_SECRET", "")
    if secret and request.headers.get("X-Push-Secret","") != secret:
        return jsonify({"ok": False, "msg": "unauthorized"}), 401

    data = request.json or {}
    if "hud" in data:
        hud.update(data["hud"])
        state["running"] = data["hud"].get("running", False)
    if "alerts" in data:
        for a in data["alerts"]:
            alerts.append(a)
        # เก็บแค่ 100 รายการล่าสุด
        while len(alerts) > 100:
            alerts.pop(0)
    return jsonify({"ok": True})


@app.route("/api/zones/delete", methods=["POST"])
def api_zones_delete():
    """ลบ zone เฉพาะชื่อออกจาก zones_config.json"""
    data     = request.json or {}
    zone_name = data.get("zone")
    cam_key  = data.get("cam", "cam_0")

    if not zone_name:
        return jsonify({"ok": False, "msg": "zone name required"})
    if not Path(ZONES_CONFIG).exists():
        return jsonify({"ok": False, "msg": "zones_config.json not found"})

    with open(ZONES_CONFIG) as f:
        cfg = json.load(f)

    cam_zones = cfg.get(cam_key, {})
    if zone_name not in cam_zones:
        return jsonify({"ok": False, "msg": f"zone '{zone_name}' not found"})

    del cam_zones[zone_name]
    cfg[cam_key] = cam_zones

    with open(ZONES_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)

    return jsonify({"ok": True, "deleted": zone_name,
                    "remaining": list(cam_zones.keys())})

@app.route("/api/zones/clear", methods=["POST"])
def api_zones_clear():
    """ล้าง zone ทั้งหมด"""
    cam_key = (request.json or {}).get("cam", "cam_0")
    if Path(ZONES_CONFIG).exists():
        with open(ZONES_CONFIG) as f:
            cfg = json.load(f)
        cfg[cam_key] = {}
        with open(ZONES_CONFIG, "w") as f:
            json.dump(cfg, f, indent=2)
    return jsonify({"ok": True})

# ── Engine ────────────────────────────────────────────────────────────────────
def engine_loop():
    from ultralytics import YOLO
    from zones           import ZoneManager
    from behavior_engine import BehaviorInferenceEngine, BehaviorType
    from tracker         import PersonTracker
    from dashboard       import draw_overlay, draw_hud
    from alert           import check_alert
    from logger          import BehaviorLogger

    print("[Engine] loading model...")
    model = YOLO(MODEL_PATH)

    try:
        zm = ZoneManager(ZONES_CONFIG)
    except FileNotFoundError:
        print("[Engine] zones_config.json not found!")
        state["running"] = False
        return

    engine  = BehaviorInferenceEngine(ZONES_CONFIG)
    logger  = BehaviorLogger(DB_PATH)
    tracker = PersonTracker()
    engine.DWELL_INTERESTED      = state["dwell_interested"]
    engine.DWELL_LOITERING       = state["dwell_loitering"]
    engine.DWELL_CHECKOUT_MIN    = state["dwell_checkout_min"]
    engine.DWELL_SEATING_WAITING = state["dwell_seating_waiting"]

    zones_poly = zm.get_polygons("cam_0")

    # open stream
    print(f"[Engine] opening stream: {state['rtsp_url']}")
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
    cap = cv2.VideoCapture(state["rtsp_url"], cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print("[Engine] ERROR: stream failed")
        state["running"] = False
        return

    # drain buffer
    for _ in range(10):
        cap.read()

    print("[Engine] stream OK — running detection")
    frame_no = 0
    fails    = 0
    CLEANUP  = 300

    while not stop_evt.is_set():
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            fails += 1
            if fails > 20:
                print("[Engine] reconnecting...")
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(state["rtsp_url"], cv2.CAP_FFMPEG)
                for _ in range(10): cap.read()
                fails = 0
            time.sleep(0.05)
            continue
        fails = 0
        frame_no += 1

        # push raw frame for smooth stream (ทุก frame)
        # ใช้ขนาดจริงของ frame ไม่ resize เพื่อให้ zone ตรง
        h_raw, w_raw = frame.shape[:2]
        if w_raw > 1280:
            display_raw = cv2.resize(frame.copy(), (1280, int(h_raw*1280/w_raw)))
        else:
            display_raw = frame.copy()
        try:
            frame_q.put_nowait(display_raw)
        except queue.Full:
            try: frame_q.get_nowait()
            except: pass
            try: frame_q.put_nowait(display_raw)
            except: pass

        # detect ทุก 2 frame เพื่อประหยัด CPU
        if frame_no % 2 != 0:
            continue

        # Auto-adjust confidence ตามเวลา
        # กลางวัน 10:00-16:00 แสงจ้า/backlight → ลด conf ลง 0.10 อัตโนมัติ
        import datetime as _dt
        _hour = _dt.datetime.now().hour
        _conf = max(0.15, state["conf"] - 0.10) if 10 <= _hour <= 16 else state["conf"]

        try:
            results = model.track(
                frame, classes=[0], conf=_conf,
                tracker="bytetrack.yaml", persist=True, verbose=False,
            )[0]
        except Exception as e:
            print(f"[Engine] track err: {e}")
            continue

        persons     = tracker.update(results, cam_key="cam_0")
        states      = {}
        active_keys = set()

        for p in persons:
            st = engine.infer(p, cam_key="cam_0")
            states[p["state_key"]] = st
            active_keys.add(p["state_key"])
            logger.log(st, cam_key="cam_0")

            if check_alert(st, cam_key="cam_0"):
                alerts.append({
                    "time":     time.strftime("%H:%M:%S"),
                    "person":   st.person_id,
                    "zone":     st.zone,
                    "behavior": st.behavior.value,
                })
                if len(alerts) > 100:
                    alerts.pop(0)

        hud["cust"]   = sum(1 for s in states.values() if not s.is_seller)
        hud["seller"] = sum(1 for s in states.values() if s.is_seller)
        hud["alert"]  = sum(1 for s in states.values() if s.needs_staff)

        if frame_no % CLEANUP == 0:
            tracker.cleanup(active_keys)

        # draw annotated frame — scale เหมือน raw frame
        h_d, w_d = frame.shape[:2]
        if w_d > 1280:
            display = cv2.resize(frame.copy(), (1280, int(h_d*1280/w_d)))
            # scale zones_poly ลงตาม ratio
            scale_x = 1280 / w_d
            scale_y = (int(h_d*1280/w_d)) / h_d
            scaled_poly = {}
            for zn, poly in zones_poly.items():
                import numpy as np
                sp = poly.copy().astype(float)
                sp[:,0] *= scale_x
                sp[:,1] *= scale_y
                scaled_poly[zn] = sp.astype(int)
            display = draw_overlay(display, persons, states, scaled_poly,
                                   anonymize=state["anonymize"])
        else:
            display = frame.copy()
            display = draw_overlay(display, persons, states, zones_poly,
                                   anonymize=state["anonymize"])
        display = draw_hud(display, "cam_0", states)

        try:
            frame_q.put_nowait(display)
        except queue.Full:
            try: frame_q.get_nowait()
            except: pass
            try: frame_q.put_nowait(display)
            except: pass

    cap.release()
    logger.close()
    state["running"] = False
    print("[Engine] stopped")

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = open(Path(__file__).parent / "templates" / "index.html",
            encoding="utf-8").read()

@app.route("/")
def index():
    return render_template_string(HTML)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except:
        ip = "localhost"
    print(f"\n{'='*50}")
    print(f"  Wine AI Web Server")
    print(f"  Local:   http://localhost:5000")
    print(f"  Network: http://{ip}:5000")
    print(f"{'='*50}\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
