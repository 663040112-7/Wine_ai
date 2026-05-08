import cv2
import numpy as np
from behavior_engine import BehaviorType

BEHAVIOR_COLORS = {
    "entering":       ( 80, 255, 255),   # ฟ้าอ่อน
    "moving":         (160, 160, 160),   # เทา — เดินในร้าน
    "idle":           (120, 120, 120),   # เทาเข้ม — ยืนเฉย
    "wine_browsing":  (200, 200,  50),   # ทอง — ดูไวน์อยู่
    "interested":     ( 30, 165, 255),   # ส้ม — สนใจ
    "loitering":      (  0,   0, 255),   # แดง — อยู่นานเกิน
    "processing":     (  0, 220, 255),   # ฟ้าสด — จ่ายเงิน
    "purchasing":     ( 50, 255, 100),   # เขียว — รอจ่ายเงิน
    "being_assisted": (180, 255, 180),   # เขียวอ่อน — มี seller ช่วย
    "bar_waiting":    (200, 130, 255),   # ม่วงอ่อน — บาร์
    "seated":         (255, 200, 100),   # ส้มอ่อน
    "waiting":        (  0,  80, 255),   # แดงเข้ม — รอนาน
    "seller":         (  0, 200, 255),   # เหลือง — พนักงาน
    "unknown":        (100, 100, 100),
}

SELLER_BEHAVIOR = {BehaviorType.SELLER}


def draw_overlay(frame, persons: list, states: dict,
                 zones_poly: dict,
                 anonymize: bool = False) -> np.ndarray:
    overlay = frame.copy()

    from zones import get_zone_color
    for zname, poly in zones_poly.items():
        col = get_zone_color(zname)
        cv2.fillPoly(overlay, [poly], col)
        cv2.polylines(overlay, [poly], True, col, 2)
        cx, cy = poly.mean(axis=0).astype(int)
        cv2.putText(overlay, zname, (int(cx) - 40, int(cy)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)
    cv2.addWeighted(overlay, 0.18, frame, 0.82, 0, frame)

    for p in persons:
        state = states.get(p["state_key"])
        if state is None:
            continue

        x1, y1, x2, y2 = p["bbox"]
        behavior = state.behavior.value
        col      = BEHAVIOR_COLORS.get(behavior, (200, 200, 200))
        is_seller = state.is_seller

        # Anonymization — เบลอส่วนหัว (1/3 บนของ bounding box)
        if anonymize:
            head_h = (y2 - y1) // 3
            hy1 = max(0, y1)
            hy2 = min(frame.shape[0], y1 + head_h)
            hx1 = max(0, x1)
            hx2 = min(frame.shape[1], x2)
            if hy2 > hy1 and hx2 > hx1:
                roi = frame[hy1:hy2, hx1:hx2]
                frame[hy1:hy2, hx1:hx2] = cv2.GaussianBlur(roi, (51, 51), 0)

        if is_seller:
            # กรอบประ = seller
            for i in range(0, x2 - x1, 10):
                cv2.line(frame, (x1+i, y1), (min(x1+i+5, x2), y1), col, 2)
                cv2.line(frame, (x1+i, y2), (min(x1+i+5, x2), y2), col, 2)
            for i in range(0, y2 - y1, 10):
                cv2.line(frame, (x1, y1+i), (x1, min(y1+i+5, y2)), col, 2)
                cv2.line(frame, (x2, y1+i), (x2, min(y1+i+5, y2)), col, 2)
            label = f"SELLER #{p['id']}"
        else:
            cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)
            label = f"#{p['id']} {behavior}"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.rectangle(frame, (x1, y1-th-8), (x1+tw+6, y1), col, -1)
        cv2.putText(frame, label, (x1+3, y1-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 2)

        if state.needs_staff and not is_seller:
            cv2.putText(frame, "! ASSIST", (x1, y2+18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 50, 255), 2)

        for tx, ty in p["trajectory"][-20:]:
            cv2.circle(frame, (tx, ty), 2, col, -1)

    return frame


def draw_hud(frame, cam_key: str, states: dict,
             is_paused: bool = False) -> np.ndarray:
    n_seller    = sum(1 for s in states.values() if s.is_seller)
    n_customer  = sum(1 for s in states.values() if not s.is_seller)
    n_alert     = sum(1 for s in states.values() if s.needs_staff)
    n_process   = sum(1 for s in states.values()
                      if s.behavior == BehaviorType.PROCESSING)

    hud = (f"{cam_key}  "
           f"cust:{n_customer}  "
           f"seller:{n_seller}  "
           f"processing:{n_process}  "
           f"alert:{n_alert}")
    if is_paused:
        hud += "  [PAUSED]"
    cv2.putText(frame, hud, (10, frame.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return frame
