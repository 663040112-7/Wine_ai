# =============================================================================
# zone_setup.py
# Usage:
#   python zone_setup.py cam0.mp4 cam1.mp4 cam2.mp4
#   python zone_setup.py 0 1 2
#   python zone_setup.py --zones counter cam0.mp4
#   python zone_setup.py --cam 1 cam1.mp4
#
# Controls:
#   Left click  = add point
#   Right click = save zone (need >= 3 points)
#   Q           = skip zone
# =============================================================================
import sys
import os
import cv2
from zones import ZoneSetup, CAMERA_ZONE_MAP, ZONE_COLORS

VIDEO_W, VIDEO_H = 960, 540


def grab_frame(source) -> tuple:
    """image: auto-resize to 960x540. video: slider to pick frame."""
    if isinstance(source, str):
        ext = os.path.splitext(source)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            frame = cv2.imread(source)
            if frame is None:
                print(f"  cannot read: {source}")
                return False, None
            h, w = frame.shape[:2]
            if w != VIDEO_W or h != VIDEO_H:
                print(f"  resize {w}x{h} -> {VIDEO_W}x{VIDEO_H}")
                frame = cv2.resize(frame, (VIDEO_W, VIDEO_H))
            return True, frame

    cap   = cv2.VideoCapture(source)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total <= 0:
        ret, frame = cap.read()
        cap.release()
        return ret, frame

    # slider to pick frame
    win = "Select frame — ENTER=select  Q=cancel"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, VIDEO_W, VIDEO_H)
    pos = [total // 3]
    cv2.createTrackbar("Frame", win, pos[0], total - 1,
                       lambda v: pos.__setitem__(0, v))
    selected = [None]

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos[0])
        ret, frame = cap.read()
        if not ret:
            break
        fps  = cap.get(cv2.CAP_PROP_FPS) or 20
        ts   = pos[0] / fps
        info = f"Frame {pos[0]}/{total-1}  ({ts:.1f}s)  ENTER=select  Q=cancel"
        disp = frame.copy()
        cv2.putText(disp, info, (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
        cv2.putText(disp, info, (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        cv2.imshow(win, disp)
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 32):
            selected[0] = frame.copy()
            break
        elif key == ord('q'):
            break

    cv2.destroyWindow(win)
    cap.release()
    return (True, selected[0]) if selected[0] is not None else (False, None)


def parse_args(argv: list):
    sources     = []
    zone_filter = None
    cam_only    = None
    i = 0
    while i < len(argv):
        if argv[i] == "--zones":
            zone_filter = []
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                zone_filter.append(argv[i])
                i += 1
        elif argv[i] == "--cam":
            i += 1
            cam_only = int(argv[i])
            i += 1
        else:
            try:
                sources.append(int(argv[i]))
            except ValueError:
                sources.append(argv[i])
            i += 1
    if not sources:
        sources = [0]
    return sources, zone_filter, cam_only


def main():
    sources, zone_filter, cam_only = parse_args(sys.argv[1:])
    setup = ZoneSetup("zones_config.json")

    for i, src in enumerate(sources):
        if cam_only is not None and i != cam_only:
            continue

        cam_key    = f"cam_{i}"
        zone_order = zone_filter or CAMERA_ZONE_MAP.get(cam_key,
                                      list(ZONE_COLORS.keys()))

        print(f"\n{'='*60}")
        print(f"cam_{i}  source: {src}")
        print(f"Zones: {zone_order}")
        print("Lclick=add  Rclick=save  Q=skip")

        ret, frame = grab_frame(src)
        if not ret or frame is None:
            print(f"  cannot open: {src}")
            continue

        setup.setup_for_camera(i, frame, zone_order=zone_order)

    print("\ndone — zones_config.json updated")


if __name__ == "__main__":
    main()
