# =============================================================================
# main.py — Wine AI Customer Behavior Detection
#
# Usage:
#   python main.py cam0.mp4 cam1.mp4          sequential (default)
#   python main.py --parallel cam0.mp4 cam1.mp4   parallel (2 windows)
#   python main.py 0 1                        webcam
#   python main.py rtsp://... rtsp://...      IP camera
#
# Keys: SPACE=pause  ENTER=next  R=replay  Q=quit all
# =============================================================================
import os
import re
from datetime import datetime
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import sys
import cv2
import threading
import numpy as np
from ultralytics import YOLO

from tracker         import PersonTracker
from behavior_engine import BehaviorInferenceEngine
from dashboard       import draw_overlay, draw_hud
from alert           import check_alert
from logger          import BehaviorLogger
from zones           import ZoneManager
from data_manager    import DataManager

MODEL_PATH    = "yolov8n.pt"
CONF          = 0.40
CLEANUP_EVERY = 300


def parse_args(argv: list):
    """
    คืน (sources, cam_keys, parallel_mode)
    รองรับ:
      cam0.mp4 cam1.mp4             → cam_0, cam_1
      cam0.mp4:cam_0 cam1.mp4:cam_1 → explicit cam keys
      --parallel                     → parallel mode flag
    """
    parallel  = "--parallel"  in argv
    anonymize = "--anonymize" in argv
    argv      = [a for a in argv if a not in ("--parallel", "--anonymize")]

    sources, cam_keys = [], []
    for i, s in enumerate(argv if argv else ["0"]):
        if ":" in s and not s.startswith("rtsp"):
            parts = s.rsplit(":", 1)
            src, key = parts[0], parts[1]
        else:
            src, key = s, f"cam_{i}"
        try:
            src = int(src)
        except (ValueError, TypeError):
            pass
        sources.append(src)
        cam_keys.append(key)

    return sources, cam_keys, parallel, anonymize


# =============================================================================
# Sequential mode — รัน camera ทีละตัว
# =============================================================================
def run_camera_sequential(source, cam_key: str, model,
                          zone_manager: ZoneManager,
                          engine: BehaviorInferenceEngine,
                          logger: BehaviorLogger,
                          anonymize: bool = False) -> bool:
    """คืน True=ไปกล้องถัดไป, False=หยุดทั้งหมด"""
    tracker    = PersonTracker()
    cap        = cv2.VideoCapture(source)
    is_file    = isinstance(source, str)
    total_f    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if is_file else 0
    zones_poly = zone_manager.get_polygons(cam_key)
    paused     = False
    frame_no   = 0
    last_frame = None

    src_label = f"video:{source}" if is_file else f"webcam:{source}"
    print(f"\n>> {cam_key} ({src_label})"
          + (f"  {total_f} frames" if total_f else ""))
    print("  SPACE=pause  ENTER=next  R=replay  Q=quit")

    while cap.isOpened():
        if not paused:
            ret, frame = cap.read()
            if not ret:
                break
            last_frame = frame.copy()
            frame_no  += 1

        cur = last_frame if paused else frame

        # คำนวณ timestamp จากตำแหน่ง frame ในคลิป
        # ถ้าเป็น live camera (is_file=False) ใช้ time.time() แทน
        video_ts = None
        if is_file:
            pos_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            # ดึงวันที่จาก filename เฉพาะ video file เท่านั้น
            # pattern ต้องมี separator เช่น 2026-04-23 หรือ 2026_04_23
            date_match = re.search(r'(\d{4})[_-](\d{2})[_-](\d{2})', str(source))
            if date_match:
                y, m, d = date_match.groups()
                try:
                    if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
                        base_dt = datetime(int(y), int(m), int(d), 0, 0, 0)
                        video_ts = base_dt.timestamp() + pos_sec
                except ValueError:
                    video_ts = None

        # Auto-adjust confidence ตามเวลา
        import datetime as _dt
        _hour = _dt.datetime.now().hour
        _conf = max(0.15, CONF - 0.10) if 10 <= _hour <= 16 else CONF

        results = model.track(
            cur, classes=[0], conf=_conf,
            tracker="bytetrack.yaml", persist=True, verbose=False,
        )[0]

        persons     = tracker.update(results, cam_key=cam_key)
        states      = {}
        active_keys = set()

        for p in persons:
            state = engine.infer(p, cam_key=cam_key)
            states[p["state_key"]] = state
            active_keys.add(p["state_key"])
            check_alert(state, cam_key=cam_key)
            logger.log(state, cam_key=cam_key, video_ts=video_ts)

        if frame_no % CLEANUP_EVERY == 0:
            tracker.cleanup(active_keys)
            for key in list(engine.states.keys()):
                if key.startswith(cam_key) and key not in active_keys:
                    engine.remove(key)

        display = cur.copy()
        display = draw_overlay(display, persons, states, zones_poly, anonymize=anonymize)
        display = draw_hud(display, cam_key, states, is_paused=paused)

        if is_file and total_f > 0:
            pos   = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            bar_w = int(display.shape[1] * pos / total_f)
            cv2.rectangle(display,
                          (0, display.shape[0] - 4),
                          (bar_w, display.shape[0]),
                          (80, 200, 120), -1)

        cv2.imshow(f"Wine AI — {cam_key}", display)

        key = cv2.waitKey(1 if not paused else 40) & 0xFF
        if key == ord('q'):
            cap.release()
            cv2.destroyAllWindows()
            return False
        elif key == ord(' '):
            paused = not paused
        elif key == ord('r') and is_file:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            frame_no = 0
            print(f"  rewind {cam_key}")
        elif key == 13:
            break

    # video จบ
    if is_file and last_frame is not None:
        print(f"  {cam_key} done  |  ENTER=next  R=replay  Q=quit")
        while True:
            end = last_frame.copy()
            cv2.putText(end, "END  ENTER=next  R=replay  Q=quit",
                        (10, end.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 200, 120), 2)
            cv2.imshow(f"Wine AI — {cam_key}", end)
            key = cv2.waitKey(100) & 0xFF
            if key == ord('q'):
                cap.release()
                cv2.destroyAllWindows()
                return False
            elif key == 13:
                break
            elif key == ord('r'):
                cap.release()
                cv2.destroyAllWindows()
                return run_camera_sequential(source, cam_key, model,
                                             zone_manager, engine, logger)

    cap.release()
    cv2.destroyAllWindows()
    return True


# =============================================================================
# Parallel mode — รัน camera ทุกตัวพร้อมกันใน thread แยก
# =============================================================================
# ── Parallel helpers ──────────────────────────────────────────────────────────

class CamWorker:
    """
    Background thread ทำ detection เท่านั้น
    ส่ง display frame ผ่าน Queue กลับมาให้ main thread แสดงผล
    imshow / waitKey อยู่บน main thread เสมอ (Windows requirement)
    """
    def __init__(self, source, cam_key: str, model_path: str,
                 zone_manager: ZoneManager, engine: BehaviorInferenceEngine,
                 db_path: str, stop_event: threading.Event):
        self.cam_key     = cam_key
        self.stop_event  = stop_event
        self.frame_queue = __import__('queue').Queue(maxsize=2)

        self._t = threading.Thread(
            target=self._worker,
            args=(source, model_path, zone_manager, engine, db_path),
            daemon=True,
        )

    def start(self):
        self._t.start()

    def is_alive(self):
        return self._t.is_alive()

    def get_frame(self):
        """คืน display frame ล่าสุด หรือ None ถ้ายังไม่มี"""
        try:
            return self.frame_queue.get_nowait()
        except:
            return None

    def _worker(self, source, model_path, zone_manager,
                engine, db_path):
        model      = YOLO(model_path)
        logger     = BehaviorLogger(db_path)
        tracker    = PersonTracker()
        cap        = cv2.VideoCapture(source)
        is_file    = isinstance(source, str)
        total_f    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if is_file else 0
        zones_poly = zone_manager.get_polygons(self.cam_key)
        frame_no   = 0
        last_frame = None

        src_label = f"video:{source}" if is_file else f"webcam:{source}"
        print(f"  [parallel] {self.cam_key} ({src_label})"
              + (f"  {total_f} frames" if total_f else ""))

        while cap.isOpened() and not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                if is_file:
                    print(f"  [parallel] {self.cam_key} done")
                break
            last_frame = frame.copy()
            frame_no  += 1

            try:
                results = model.track(
                    frame, classes=[0], conf=CONF,
                    tracker="bytetrack.yaml", persist=True, verbose=False,
                )[0]
            except Exception as e:
                print(f"  [{self.cam_key}] track error: {e}")
                break

            persons     = tracker.update(results, cam_key=self.cam_key)
            states      = {}
            active_keys = set()

            for p in persons:
                state = engine.infer(p, cam_key=self.cam_key)
                states[p["state_key"]] = state
                active_keys.add(p["state_key"])
                check_alert(state, cam_key=self.cam_key)
                logger.log(state, cam_key=self.cam_key)

            if frame_no % CLEANUP_EVERY == 0:
                tracker.cleanup(active_keys)
                for key in list(engine.states.keys()):
                    if key.startswith(self.cam_key) and key not in active_keys:
                        engine.remove(key)

            # สร้าง display frame แล้วส่งไปให้ main thread
            display = frame.copy()
            display = draw_overlay(display, persons, states, zones_poly, anonymize=anonymize)
            display = draw_hud(display, self.cam_key, states)

            if is_file and total_f > 0:
                pos   = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                bar_w = int(display.shape[1] * pos / total_f)
                cv2.rectangle(display,
                              (0, display.shape[0] - 4),
                              (bar_w, display.shape[0]),
                              (80, 200, 120), -1)

            # ใส่ใน queue (drop ถ้า queue เต็ม — ไม่ block)
            try:
                self.frame_queue.put_nowait(display)
            except:
                pass

        logger.close()
        cap.release()


def run_parallel(sources, cam_keys, zone_manager, engine):
    """
    Main thread จัดการ imshow ทั้งหมด
    Background threads ทำ detection แล้วส่ง frame มาผ่าน Queue
    """
    stop_event = threading.Event()
    workers    = []

    print(f"\n>> Parallel mode — {len(sources)} cameras")
    print("  Q = quit all")

    for src, cam_key in zip(sources, cam_keys):
        w = CamWorker(src, cam_key, MODEL_PATH, zone_manager,
                      engine, "behavior_log.db", stop_event)
        w.start()
        workers.append(w)

    # main thread — imshow + waitKey
    while any(w.is_alive() for w in workers):
        for w in workers:
            frame = w.get_frame()
            if frame is not None:
                cv2.imshow(f"Wine AI — {w.cam_key}", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("  Quit...")
            stop_event.set()
            break

    stop_event.set()
    for w in workers:
        w._t.join(timeout=5)
    cv2.destroyAllWindows()


# =============================================================================
# main
# =============================================================================
def main():
    sources, cam_keys, parallel, anonymize = parse_args(sys.argv[1:])
    model = YOLO(MODEL_PATH)

    try:
        zone_manager = ZoneManager("zones_config.json")
    except FileNotFoundError:
        print("zones_config.json not found — run zone_setup.py first")
        sys.exit(1)

    engine = BehaviorInferenceEngine("zones_config.json")
    logger = BehaviorLogger("behavior_log.db")

    # Auto cleanup — ลบข้อมูลเก่ากว่า 30 วัน ทุกครั้งที่รัน
    DataManager().run_daily_cleanup()

    try:
        if parallel:
            run_parallel(sources, cam_keys, zone_manager, engine)
        else:
            for src, cam_key in zip(sources, cam_keys):
                keep_going = run_camera_sequential(
                    src, cam_key, model, zone_manager, engine, logger,
                    anonymize=anonymize)
                if not keep_going:
                    break
    finally:
        logger.close()
        print("done")


if __name__ == "__main__":
    main()
