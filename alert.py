import time
from behavior_engine import BehaviorType, PersonState

ALERT_COOLDOWN_SEC = 20
_last_alert: dict[str, float] = {}

ALERT_MESSAGES = {
    BehaviorType.INTERESTED:  "Customer studying wine shelf — send seller to assist",
    BehaviorType.LOITERING:   "Customer at wine shelf too long — urgent assistance needed",
    BehaviorType.PURCHASING:  "Customer at checkout — no seller present",
    BehaviorType.WAITING:     "Customer waiting too long at table — please serve",
}

# ไม่ alert behaviors เหล่านี้
NO_ALERT_BEHAVIORS = {
    BehaviorType.SELLER,
    BehaviorType.BEING_ASSISTED,
    BehaviorType.PROCESSING,
    BehaviorType.BAR_WAITING,
    BehaviorType.MOVING,
    BehaviorType.IDLE,
    BehaviorType.WINE_BROWSING,
    BehaviorType.ENTERING,
}


def check_alert(state: PersonState, cam_key: str = "cam_0") -> bool:
    if state.behavior in NO_ALERT_BEHAVIORS:
        return False
    if not state.needs_staff:
        return False

    key = f"{cam_key}_{state.person_id}"
    now = time.time()
    if now - _last_alert.get(key, 0) < ALERT_COOLDOWN_SEC:
        return False

    _last_alert[key] = now
    state.alert_sent  = True
    msg = ALERT_MESSAGES.get(state.behavior, "Customer needs assistance")
    print(
        f"\n{'='*55}\n"
        f"  ALERT [{cam_key}] Customer #{state.person_id}\n"
        f"  Zone    : {state.zone}\n"
        f"  Behavior: {state.behavior.value}\n"
        f"  Message : {msg}\n"
        f"{'='*55}"
    )
    return True


def send_line_notify(message: str, token: str = ""):
    if not token:
        return
    try:
        import urllib.request, urllib.parse
        data = urllib.parse.urlencode({"message": message}).encode()
        req  = urllib.request.Request(
            "https://notify-api.line.me/api/notify", data=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        print(f"[Line Notify] error: {e}")
