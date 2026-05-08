# =============================================================================
# tracker.py — PersonTracker using ByteTrack (built into ultralytics)
# =============================================================================
from collections import defaultdict


class PersonTracker:
    """
    รับ results จาก YOLO.track() แล้ว assign ID + เก็บ trajectory
    ByteTrack ถูก call ใน main.py ผ่าน model.track(..., tracker='bytetrack.yaml')
    """

    def __init__(self, max_history: int = 60):
        self.max_history = max_history   # จำนวน frame ที่เก็บ path (60f ≈ 2s @30fps)
        self.trajectories: dict[str, list[tuple]] = defaultdict(list)

    def update(self, tracked_results, cam_key: str = "cam_0") -> list[dict]:
        """
        แปลง YOLO track results → list of person dicts
        state_key = cam_key + track_id เพื่อไม่ให้ ID ชนกันระหว่างกล้อง

        Returns:
            [{"id": int, "state_key": str, "bbox": [...], "center": (cx, cy),
              "trajectory": [(cx,cy), ...]}, ...]
        """
        persons = []
        if tracked_results.boxes.id is None:
            return persons

        for box, track_id in zip(tracked_results.boxes, tracked_results.boxes.id):
            pid       = int(track_id)
            state_key = f"{cam_key}_{pid}"
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cx = (x1 + x2) // 2
            cy = y2   # bottom center — เท้าคน แม่นกว่าสำหรับ zone check

            self.trajectories[state_key].append((cx, cy))
            if len(self.trajectories[state_key]) > self.max_history:
                self.trajectories[state_key].pop(0)

            persons.append({
                "id":         pid,
                "state_key":  state_key,
                "bbox":       [x1, y1, x2, y2],
                "center":     (cx, cy),
                "trajectory": list(self.trajectories[state_key]),
            })
        return persons

    def cleanup(self, active_keys: set[str]):
        """ลบ trajectory ของ person ที่ออกไปแล้ว (เรียกทุก N frame)"""
        for key in list(self.trajectories.keys()):
            if key not in active_keys:
                del self.trajectories[key]
