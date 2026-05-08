# =============================================================================
# detector.py — PersonDetector using YOLOv8n pretrained (COCO person class 0)
# =============================================================================
from ultralytics import YOLO


class PersonDetector:
    """
    Wraps YOLOv8n — filters class 0 (person) only.
    Model auto-downloads on first run from Ultralytics CDN.
    """

    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.4, device: str = "cpu"):
        self.model  = YOLO(model_path)
        self.conf   = conf
        self.device = device
        print(f"[PersonDetector] model={model_path}  conf={conf}  device={device}")

    def detect(self, frame) -> list[dict]:
        """
        Returns list of detections (person only):
        [{"bbox": [x1, y1, x2, y2], "conf": float}, ...]
        """
        results = self.model(
            frame,
            classes=[0],        # 0 = person (COCO)
            conf=self.conf,
            device=self.device,
            verbose=False,
        )[0]

        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append({
                "bbox": [x1, y1, x2, y2],
                "conf": float(box.conf[0]),
            })
        return detections
