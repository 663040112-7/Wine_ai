# =============================================================================
# logger.py — SQLite event logger
# อัปเดต: รองรับ video_timestamp จากคลิปแทน time.time()
# =============================================================================
import sqlite3
import time
from behavior_engine import PersonState

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      REAL,
    cam_key        TEXT,
    person_id      INTEGER,
    zone           TEXT,
    behavior       TEXT,
    needs_staff    INTEGER,
    is_new_visit   INTEGER DEFAULT 1
)
"""

class BehaviorLogger:
    FLUSH_EVERY = 30
    # cooldown กี่วินาทีก่อนนับ person เดิมว่า "ใหม่" อีกครั้ง
    # ถ้า person หายไปน้อยกว่า 120 วิ ไม่นับใหม่
    PERSON_COOLDOWN_SEC = 120

    def __init__(self, db_path: str = "behavior_log.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(CREATE_SQL)
        self.conn.commit()
        self._buf: list = []
        # track เวลาที่เห็น person_id แต่ละตัวล่าสุด
        self._seen: dict = {}
        print(f"[Logger] db → {db_path}")

    def log(self, state: PersonState, cam_key: str = "cam_0",
            video_ts: float = None):
        """
        video_ts: Unix timestamp จาก frame ของคลิป
                  ถ้าเป็น None จะใช้ time.time() แทน (live camera)
        """
        ts  = video_ts if video_ts is not None else time.time()
        key = f"{cam_key}_{state.person_id}"

        # Log ทุก frame แต่ mark is_new_visit
        # สำหรับนับ unique person ใน report ใช้ cooldown
        last_seen = self._seen.get(key, 0)
        is_new    = (ts - last_seen) > self.PERSON_COOLDOWN_SEC
        self._seen[key] = ts

        self._buf.append((
            ts, cam_key,
            state.person_id, state.zone,
            state.behavior.value, int(state.needs_staff),
            int(is_new),   # 1 = นับเป็นคนใหม่, 0 = คนเดิมยังอยู่
        ))
        if len(self._buf) >= self.FLUSH_EVERY:
            self._flush()

    def _flush(self):
        if self._buf:
            self.conn.executemany(
                "INSERT INTO events (timestamp,cam_key,person_id,zone,behavior,needs_staff,is_new_visit)"
                " VALUES (?,?,?,?,?,?,?)",
                self._buf,
            )
            self.conn.commit()
            self._buf.clear()

    def close(self):
        self._flush()
        self.conn.close()
        print("[Logger] closed.")
