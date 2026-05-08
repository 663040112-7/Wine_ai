import cv2
import json
import numpy as np
from pathlib import Path

ZONE_COLORS = {
    "wine_left":        ( 50, 200, 100),
    "wine_right":       ( 50, 200, 100),
    "wine_back":        ( 50, 200, 100),
    "counter_checkout": (255,  60, 120),   # ชมพูสด — จ่ายเงิน (สำคัญสุด)
    "counter_bar":      (200, 100, 255),   # ม่วง — นั่งรอ/บาร์
    "seller_zone":      (  0, 200, 255),   # เหลือง — พื้นที่พนักงานขาย
    "seating":          ( 50, 165, 255),   # ส้ม
    "entrance":         ( 80, 255, 200),   # เขียวอ่อน
}

ZONE_COLOR_RULES = {
    "wine":             ( 50, 200, 100),
    "counter_checkout": (255,  60, 120),
    "counter_bar":      (200, 100, 255),
    "seller_zone":      (  0, 200, 255),
    "seating":          ( 50, 165, 255),
    "entrance":         ( 80, 255, 200),
}

def get_zone_color(zone_name: str) -> tuple:
    for prefix, color in ZONE_COLOR_RULES.items():
        if zone_name.startswith(prefix):
            return color
    return ZONE_COLORS.get(zone_name, (128, 128, 128))

ZONE_BEHAVIOR_PREFIX = {
    "seller_zone":      "staff",
    "wine":             "browsing",
    "counter_checkout": "purchasing",
    "counter_bar":      "waiting",
    "seating":          "seated",
    "entrance":         "entering",
}

def get_zone_behavior(zone_name: str) -> str:
    for prefix, behavior in ZONE_BEHAVIOR_PREFIX.items():
        if zone_name.startswith(prefix):
            return behavior
    return "browsing"

# Priority — higher number wins when zones overlap
ZONE_PRIORITY = {
    "seller_zone":      10,
    "counter_checkout":  9,
    "counter_bar":       7,
    "seating":           6,
    "entrance":          4,
    "wine":              2,
    "floor":             0,
}

def get_zone_priority(zone_name: str) -> int:
    for prefix, score in ZONE_PRIORITY.items():
        if zone_name.startswith(prefix):
            return score
    return 0

# Zones each camera should draw
CAMERA_ZONE_MAP = {
    "cam_0": ["wine_left", "wine_right",
              "counter_checkout", "counter_bar",
              "seller_zone", "seating"],
    "cam_1": ["entrance", "wine_left", "wine_right", "seating"],
}


class ZoneSetup:
    def __init__(self, config_path: str = "zones_config.json"):
        self.config_path = Path(config_path)
        self.all_cameras: dict = {}

    def setup_for_camera(self, camera_id, frame, zone_order: list = None):
        if zone_order is None:
            zone_order = list(ZONE_COLORS.keys())

        cam_key  = f"cam_{camera_id}"
        zones    = {}
        cur_pts  = []
        cur_name = [""]

        def mouse_cb(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                cur_pts.append([x, y])
            elif event == cv2.EVENT_RBUTTONDOWN and len(cur_pts) >= 3:
                zones[cur_name[0]] = list(cur_pts)
                print(f"  saved '{cur_name[0]}' ({len(cur_pts)} pts)")
                cur_pts.clear()

        win = f"Zone Setup — cam_{camera_id}"
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, mouse_cb)

        for name in zone_order:
            cur_name[0] = name
            cur_pts.clear()
            print(f"\n  [{name}]  Lclick=add  Rclick=save  Q=skip")

            while True:
                display = frame.copy()

                for zname, pts in zones.items():
                    poly = np.array(pts)
                    col  = get_zone_color(zname)
                    over = display.copy()
                    cv2.fillPoly(over, [poly], col)
                    cv2.addWeighted(over, 0.15, display, 0.85, 0, display)
                    cv2.polylines(display, [poly], True, col, 2)
                    cx, cy = poly.mean(axis=0).astype(int)
                    cv2.putText(display, zname, (int(cx) - 40, int(cy)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)

                col_cur = get_zone_color(name)
                for pt in cur_pts:
                    cv2.circle(display, tuple(pt), 5, col_cur, -1)
                if len(cur_pts) > 1:
                    cv2.polylines(display,
                                  [np.array(cur_pts)], False, col_cur, 1)

                # outline สีดำ
                cv2.putText(display,
                            f"Zone: {name}  pts:{len(cur_pts)}  Rclick=save  Q=skip",
                            (10, 75), cv2.FONT_HERSHEY_SIMPLEX,
                            0.65, (0, 0, 0), 4)
                # text สีขาว
                cv2.putText(display,
                            f"Zone: {name}  pts:{len(cur_pts)}  Rclick=save  Q=skip",
                            (10, 75), cv2.FONT_HERSHEY_SIMPLEX,
                            0.65, (255, 255, 255), 2)
                cv2.imshow(win, display)

                key = cv2.waitKey(30) & 0xFF
                if key == ord('q') or name in zones:
                    break

        cv2.destroyWindow(win)
        self.all_cameras[cam_key] = zones

        existing = {}
        if self.config_path.exists():
            with open(self.config_path) as f:
                existing = json.load(f)
        if cam_key not in existing:
            existing[cam_key] = {}
        existing[cam_key].update(zones)
        with open(self.config_path, "w") as f:
            json.dump(existing, f, indent=2)
        print(f"\n  saved [{cam_key}]: {list(zones.keys())}")


class ZoneManager:
    def __init__(self, config_path: str = "zones_config.json"):
        with open(config_path) as f:
            raw = json.load(f)
        if any(k.startswith("cam_") for k in raw):
            self.cameras = {
                cam: {z: np.array(pts) for z, pts in zones.items()}
                for cam, zones in raw.items()
            }
        else:
            self.cameras = {"cam_0": {z: np.array(pts) for z, pts in raw.items()}}

    def get_zone(self, cx: int, cy: int, cam_key: str = "cam_0") -> str:
        matched = []
        for name, poly in self.cameras.get(cam_key, {}).items():
            if cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0:
                matched.append(name)
        if not matched:
            return "floor"
        if len(matched) == 1:
            return matched[0]
        return max(matched, key=get_zone_priority)

    def is_seller_zone(self, zone_name: str) -> bool:
        return zone_name.startswith("seller_zone")

    def get_polygons(self, cam_key: str = "cam_0") -> dict:
        return self.cameras.get(cam_key, {})
