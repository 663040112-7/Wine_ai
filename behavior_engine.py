import cv2
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from zones import ZoneManager


class BehaviorType(Enum):
    UNKNOWN          = "unknown"
    ENTERING         = "entering"
    MOVING           = "moving"
    IDLE             = "idle"
    WINE_BROWSING    = "wine_browsing"
    INTERESTED       = "interested"
    LOITERING        = "loitering"
    PROCESSING       = "processing"
    PURCHASING       = "purchasing"
    BEING_ASSISTED   = "being_assisted"
    BAR_WAITING      = "bar_waiting"
    SEATED           = "seated"
    WAITING          = "waiting"
    SELLER           = "seller"


@dataclass
class PersonState:
    person_id:   int
    cam_key:     str   = "cam_0"
    zone:        str   = "unknown"
    dwell_start: float = field(default_factory=time.time)
    behavior:    BehaviorType = BehaviorType.UNKNOWN
    needs_staff: bool  = False
    last_center: tuple = (0, 0)
    alert_sent:  bool  = False
    is_seller:   bool  = False


class BehaviorInferenceEngine:
    DWELL_INTERESTED      = 25    # วิ — อ่าน label ไวน์ใช้เวลา
    DWELL_LOITERING       = 90    # วิ — อยู่นานเกิน = ต้องการความช่วยเหลือ
    DWELL_CHECKOUT_MIN    = 5     # วิ — counter แคบ รอ 5+ วิ
    DWELL_SEATING_WAITING = 180   # วิ — 3 นาทีไม่มีคนเสิร์ฟ
    VELOCITY_STILL_PX     = 3.0   # px/frame — ร้านเล็กคนเดินช้า
    SELLER_PROXIMITY_PX   = 150   # px — ร้านแคบ

    def __init__(self, config_path: str = "zones_config.json"):
        self.zone_manager = ZoneManager(config_path)
        self.states: dict[str, PersonState] = {}

    def _velocity(self, trajectory: list) -> float:
        if len(trajectory) < 2:
            return 0.0
        dx = trajectory[-1][0] - trajectory[-2][0]
        dy = trajectory[-1][1] - trajectory[-2][1]
        return math.sqrt(dx * dx + dy * dy)

    def _seller_nearby(self, cx, cy, cam_key, exclude_key) -> bool:
        for key, st in self.states.items():
            if key == exclude_key or not st.is_seller:
                continue
            if st.cam_key != cam_key:
                continue
            sx, sy = st.last_center
            if math.sqrt((cx-sx)**2 + (cy-sy)**2) <= self.SELLER_PROXIMITY_PX:
                return True
        return False

    def _has_seller_in_zone(self, zone_prefix, cam_key, exclude_key) -> bool:
        for key, st in self.states.items():
            if key == exclude_key or st.cam_key != cam_key:
                continue
            if st.is_seller and st.zone.startswith(zone_prefix):
                return True
        return False

    def infer(self, person: dict, cam_key: str = "cam_0") -> PersonState:
        state_key = person["state_key"]
        cx, cy    = person["center"]
        traj      = person["trajectory"]

        if state_key not in self.states:
            self.states[state_key] = PersonState(
                person_id=person["id"], cam_key=cam_key,
            )

        state        = self.states[state_key]
        current_zone = self.zone_manager.get_zone(cx, cy, cam_key)
        velocity     = self._velocity(traj)
        dwell_sec    = time.time() - state.dwell_start

        if current_zone != state.zone:
            state.zone        = current_zone
            state.dwell_start = time.time()
            state.alert_sent  = False
            dwell_sec         = 0

        state.last_center = (cx, cy)
        state.is_seller   = self.zone_manager.is_seller_zone(current_zone)

        if state.is_seller:
            state.behavior    = BehaviorType.SELLER
            state.needs_staff = False

        elif current_zone == "entrance":
            state.behavior    = BehaviorType.ENTERING
            state.needs_staff = False

        elif current_zone.startswith("wine"):
            if self._seller_nearby(cx, cy, cam_key, state_key):
                state.behavior    = BehaviorType.BEING_ASSISTED
                state.needs_staff = False
            elif dwell_sec > self.DWELL_LOITERING:
                state.behavior    = BehaviorType.LOITERING
                state.needs_staff = True
            elif dwell_sec > self.DWELL_INTERESTED:
                state.behavior    = BehaviorType.INTERESTED
                state.needs_staff = True
            else:
                state.behavior    = BehaviorType.WINE_BROWSING
                state.needs_staff = False

        elif current_zone.startswith("counter_checkout"):
            seller_present = (
                self._has_seller_in_zone("seller_zone", cam_key, state_key) or
                self._has_seller_in_zone("counter_checkout", cam_key, state_key)
            )
            if seller_present:
                state.behavior    = BehaviorType.PROCESSING
                state.needs_staff = False
            elif dwell_sec > self.DWELL_CHECKOUT_MIN:
                state.behavior    = BehaviorType.PURCHASING
                state.needs_staff = True
            else:
                state.behavior    = BehaviorType.MOVING
                state.needs_staff = False

        elif current_zone.startswith("counter_bar"):
            state.behavior    = BehaviorType.BAR_WAITING
            state.needs_staff = False

        elif current_zone == "seating":
            if dwell_sec > self.DWELL_SEATING_WAITING:
                state.behavior    = BehaviorType.WAITING
                state.needs_staff = True
            else:
                state.behavior    = BehaviorType.SEATED
                state.needs_staff = False

        else:
            if velocity > self.VELOCITY_STILL_PX:
                state.behavior    = BehaviorType.MOVING
                state.needs_staff = False
            else:
                state.behavior    = BehaviorType.IDLE
                state.needs_staff = False

        return state

    def remove(self, state_key: str):
        self.states.pop(state_key, None)

    def clear_staff_memory(self):
        pass
