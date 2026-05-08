# =============================================================================
# ai_insight.py — AI-powered daily behavior summary
# รองรับ 3 mode:
#   1. Google Gemini API (ฟรี) — ตั้ง GEMINI_API_KEY
#   2. Claude API (เสียเงิน)  — ตั้ง ANTHROPIC_API_KEY
#   3. Rule-based (ฟรี 100%) — ไม่ต้องตั้งค่าอะไร
# =============================================================================
import sqlite3
import json
import os
import urllib.request
import urllib.error
from datetime import datetime

TZ = 7


def get_daily_data(db_path: str, date_filter: str = None) -> dict:
    conn = sqlite3.connect(db_path)
    dc   = f"date(datetime(timestamp,'unixepoch','+{TZ} hours'))"
    wh   = f"AND {dc}=?" if date_filter else ""
    p    = (date_filter,) if date_filter else ()

    def q(sql, params=()):
        return conn.execute(sql, params).fetchall()

    total   = q(f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 {wh}", p)[0][0]
    if total == 0:
        total = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {wh}", p)[0][0]
    inter   = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='interested' {wh}", p)[0][0]
    purch   = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='purchasing' {wh}", p)[0][0]
    loiter  = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='loitering' {wh}", p)[0][0]
    waiting = q(f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='waiting' {wh}", p)[0][0]
    alerts  = q(f"SELECT COUNT(*) FROM events WHERE needs_staff=1 {wh}", p)[0][0]
    dr      = q(f"""SELECT
        MIN(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
        MAX(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')))
        FROM events WHERE 1=1 {wh}""", p)[0]
    hourly  = q(f"""SELECT strftime('%H',datetime(timestamp,'unixepoch','+{TZ} hours')) hr,
                          COUNT(DISTINCT person_id) n
                    FROM events WHERE 1=1 {wh} GROUP BY hr ORDER BY hr""", p)
    behs    = q(f"SELECT behavior,COUNT(*) n FROM events WHERE 1=1 {wh} GROUP BY behavior ORDER BY n DESC LIMIT 8", p)
    zones   = q(f"""SELECT zone,COUNT(*) n FROM events WHERE zone!='floor' {wh}
                    GROUP BY zone ORDER BY n DESC LIMIT 6""", p)
    conn.close()

    peak_hr = max(hourly, key=lambda r: r[1]) if hourly else ("—", 0)
    return {
        "date":           date_filter or datetime.now().strftime("%Y-%m-%d"),
        "period":         f"{dr[0] or '—'} – {dr[1] or '—'}",
        "total":          total,
        "interested":     inter,
        "purchasing":     purch,
        "loitering":      loiter,
        "waiting":        waiting,
        "alerts":         alerts,
        "peak_hour":      peak_hr[0],
        "peak_count":     peak_hr[1],
        "hourly":         [(r[0], r[1]) for r in hourly],
        "behaviors":      [(r[0], r[1]) for r in behs],
        "zones":          [(r[0], r[1]) for r in zones],
        "conversion":     round(inter/total*100, 1) if total > 0 else 0,
        "purchase_rate":  round(purch/total*100, 1) if total > 0 else 0,
    }


def build_prompt(data: dict) -> str:
    hourly_str = ", ".join([f"{h}:00={c}" for h, c in data["hourly"]]) or "no data"
    beh_str    = ", ".join([f"{b}:{c}" for b, c in data["behaviors"]]) or "no data"
    zone_str   = ", ".join([f"{z}:{c}" for z, c in data["zones"]]) or "no data"
    return f"""You are a retail analytics expert for Wine O'Clock, a wine store in Khon Kaen, Thailand.

Analyze this daily customer behavior data and give actionable insights:

DATE: {data['date']}  |  HOURS: {data['period']}
Total customers: {data['total']}
Interested in wine (> 25sec): {data['interested']} ({data['conversion']}%)
Reached checkout: {data['purchasing']} ({data['purchase_rate']}%)
Loitering (urgent help): {data['loitering']}
Waiting too long at table: {data['waiting']}
Staff alerts: {data['alerts']}
Peak hour: {data['peak_hour']}:00 ({data['peak_count']} customers)
Hourly traffic: {hourly_str}
Top behaviors: {beh_str}
Top zones: {zone_str}

Respond with exactly these 5 sections (use **Section Title** format):
**Daily Summary** - 2 sentences overview
**Peak Hours Analysis** - busiest time and staffing recommendation
**Customer Engagement** - wine interest rate analysis
**Actionable Recommendations** - exactly 3 numbered recommendations
**Staff Performance Note** - based on alert patterns

Be concise, practical, and specific to a wine store."""


# ── Gemini API ────────────────────────────────────────────────────────────────
def _call_gemini(prompt: str, api_key: str) -> str:
    url     = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"gemini-2.5-flash:generateContent?key={api_key}")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 800, "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result["candidates"][0]["content"]["parts"][0]["text"]


# ── Claude API ────────────────────────────────────────────────────────────────
def _call_claude(prompt: str, api_key: str) -> str:
    payload = json.dumps({
        "model":      "claude-haiku-4-5-20251001",
        "max_tokens": 800,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result["content"][0]["text"]


# ── Rule-based fallback ───────────────────────────────────────────────────────
def _rule_based(data: dict) -> str:
    d    = data
    out  = []

    out.append("**Daily Summary**")
    if d["total"] == 0:
        out.append("No customer activity recorded for this period.")
        return "\n".join(out)
    conv = d["conversion"]
    if conv >= 30:
        out.append(f"Excellent day — {d['total']} customers with {conv}% showing genuine wine interest.")
    elif conv >= 15:
        out.append(f"Good engagement — {d['total']} customers, {conv}% stopped to browse wine products.")
    else:
        out.append(f"{d['total']} customers visited with moderate wine engagement ({conv}%).")
    if d["purchasing"] > 0:
        out.append(f"{d['purchasing']} customer(s) reached checkout ({d['purchase_rate']}% conversion rate).")

    out.append("\n**Peak Hours Analysis**")
    if d["peak_hour"] != "—":
        ph = int(d["peak_hour"])
        if 17 <= ph <= 20:
            out.append(f"Peak at {d['peak_hour']}:00 ({d['peak_count']} customers) — evening rush. Ensure full staffing 17:00–21:00.")
        elif 11 <= ph <= 14:
            out.append(f"Peak at {d['peak_hour']}:00 ({d['peak_count']} customers) — lunch traffic. Consider lunch bundle promotions.")
        elif 19 <= ph <= 22:
            out.append(f"Peak at {d['peak_hour']}:00 ({d['peak_count']} customers) — dinner crowd. Schedule wine tasting events.")
        else:
            out.append(f"Peak at {d['peak_hour']}:00 with {d['peak_count']} customers. Schedule extra staff 30 min before peak.")

    out.append("\n**Customer Engagement**")
    if conv >= 25:
        out.append(f"Strong interest rate ({conv}%) — wine display and lighting are effective. Maintain current layout.")
    elif conv >= 10:
        out.append(f"Average interest rate ({conv}%). Improve shelf signage and consider adding price tags at eye level.")
    else:
        out.append(f"Low interest rate ({conv}%). Customers may not notice shelves — add floor markers or promotional stands.")

    out.append("\n**Actionable Recommendations**")
    recs = []
    if d["loitering"] > 2:
        recs.append(f"Staff should proactively greet customers after 30 seconds in wine zone ({d['loitering']} loitering incidents).")
    if d["waiting"] > 0:
        recs.append(f"Improve table service response time — {d['waiting']} customer(s) waited over 3 minutes.")
    if d["alerts"] > 10:
        recs.append(f"High alert volume ({d['alerts']}) — consider adding one floor staff member during peak hours.")
    if conv < 15 and d["total"] > 5:
        recs.append("Rearrange wine display — move best-sellers and promotional items to eye level near entrance.")
    if d["purchasing"] == 0 and d["total"] > 3:
        recs.append("No purchases recorded — review pricing strategy or offer a daily special/discount.")
    if d["peak_count"] > 0:
        hour_val = d["peak_hour"]
        recs.append(f"Pre-staff the {hour_val}:00 peak hour — have all staff ready 15 minutes before.")
    if not recs:
        recs = [
            "Maintain current operations — all metrics within normal range.",
            "Consider seasonal wine promotions to increase customer engagement.",
            "Review zone coverage to ensure all areas have adequate detection.",
        ]
    for i, rec in enumerate(recs[:3], 1):
        out.append(f"{i}. {rec}")

    out.append("\n**Staff Performance Note**")
    if d["alerts"] == 0:
        out.append("No alerts generated — verify system is running correctly and zones are properly configured.")
    elif d["alerts"] <= 5:
        out.append("Low alert volume suggests proactive staff or calm customer flow. Good performance today.")
    elif d["alerts"] <= 20:
        out.append(f"{d['alerts']} alerts generated. Monitor staff response times and ensure notifications are visible.")
    else:
        out.append(f"High alert count ({d['alerts']}) — review staffing levels and consider enabling mobile notifications.")

    return "\n".join(out)


# ── Main function ─────────────────────────────────────────────────────────────
def get_ai_insight(db_path: str, date_filter: str = None,
                   api_key: str = None) -> dict:
    """
    คืน dict:
      ok=True  → {"ok":True, "insight":"...", "source":"Gemini|Claude", "data":{...}}
      ok=False → {"ok":False, "fallback":"...", "source":"Auto Analysis", "data":{...}}
    """
    data = get_daily_data(db_path, date_filter)

    # ลำดับ: 1. Gemini  2. Claude  3. Rule-based
    gemini_key  = api_key or os.environ.get("GEMINI_API_KEY", "")
    claude_key  = os.environ.get("ANTHROPIC_API_KEY", "")

    prompt = build_prompt(data)

    # ── Try Gemini first ──────────────────────────────────────────────────────
    if gemini_key:
        try:
            text = _call_gemini(prompt, gemini_key)
            return {"ok": True, "insight": text, "source": "Gemini 2.5 Flash (Free)", "data": data}
        except Exception as e:
            print(f"[AI] Gemini failed: {e} — trying Claude")

    # ── Try Claude ────────────────────────────────────────────────────────────
    if claude_key:
        try:
            text = _call_claude(prompt, claude_key)
            return {"ok": True, "insight": text, "source": "Claude Haiku", "data": data}
        except Exception as e:
            print(f"[AI] Claude failed: {e} — using rule-based")

    # ── Rule-based fallback ───────────────────────────────────────────────────
    return {
        "ok":       False,
        "fallback": _rule_based(data),
        "source":   "Automated Analysis",
        "data":     data,
    }


def insight_to_html(insight_text: str) -> str:
    """แปลง insight text เป็น HTML"""
    parts = []
    for line in insight_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("**") and line.endswith("**"):
            parts.append(f'<div class="insight-section-title">{line.strip("*")}</div>')
        elif len(line) >= 2 and line[0].isdigit() and line[1] == ".":
            parts.append(f'<div class="insight-rec">{line}</div>')
        else:
            import re
            line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            parts.append(f'<p class="insight-p">{line}</p>')
    return "\n".join(parts)
