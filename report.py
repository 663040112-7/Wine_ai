# =============================================================================
# report.py — Generate HTML behavior report from behavior_log.db
# Usage:
#   python report.py                        # uses behavior_log.db
#   python report.py --db my_log.db        # custom db
#   python report.py --date 2026-04-21     # filter by date (local time)
# =============================================================================
import sqlite3
import json
import sys
import os
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ_OFFSET = 7   # GMT+7

def query(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()

def build_report(db_path: str, date_filter: str = None) -> str:
    conn = sqlite3.connect(db_path)

    date_clause = ""
    if date_filter:
        date_clause = f"""AND date(datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours')) = '{date_filter}'"""

    # KPIs
    # นับจาก is_new_visit เพื่อกัน duplicate
    total_persons = query(conn, f"SELECT COUNT(*) FROM events WHERE is_new_visit=1 {date_clause}")[0][0]
    if total_persons == 0:
        total_persons = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {date_clause}")[0][0]
    interested_persons = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='interested' {date_clause}")[0][0]
    purchasing_persons = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior IN ('queuing','purchasing') {date_clause}")[0][0]
    alert_count = query(conn, f"SELECT COUNT(*) FROM events WHERE needs_staff=1 {date_clause}")[0][0]

    top_zone = query(conn, f"""
        SELECT zone, COUNT(*) as n FROM events
        WHERE zone != 'floor' {date_clause}
        GROUP BY zone ORDER BY n DESC LIMIT 1
    """)
    top_zone_name = top_zone[0][0] if top_zone else "N/A"

    date_range = query(conn, f"""
        SELECT 
            MIN(strftime('%H:%M', datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours'))),
            MAX(strftime('%H:%M', datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours'))),
            date(datetime(MIN(timestamp),'unixepoch','+{TZ_OFFSET} hours'))
        FROM events WHERE 1=1 {date_clause}
    """)[0]
    time_start, time_end, report_date = date_range

    # Hourly persons
    hourly_persons = query(conn, f"""
        SELECT strftime('%H', datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours')) as hr,
               COUNT(DISTINCT person_id) as persons
        FROM events WHERE 1=1 {date_clause}
        GROUP BY hr ORDER BY hr
    """)

    # Behavior totals
    behavior_totals = query(conn, f"""
        SELECT behavior, COUNT(*) as n FROM events
        WHERE 1=1 {date_clause}
        GROUP BY behavior ORDER BY n DESC
    """)

    # Hourly behavior stacked
    hourly_behavior = query(conn, f"""
        SELECT strftime('%H', datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours')) as hr,
               behavior, COUNT(*) as n
        FROM events WHERE 1=1 {date_clause}
        GROUP BY hr, behavior ORDER BY hr, behavior
    """)

    # Zone activity
    zone_activity = query(conn, f"""
        SELECT zone, COUNT(*) as n FROM events
        WHERE zone != 'floor' {date_clause}
        GROUP BY zone ORDER BY n DESC
    """)

    # Interested timeline
    interested_tl = query(conn, f"""
        SELECT strftime('%H:%M', datetime(timestamp,'unixepoch','+{TZ_OFFSET} hours')) as t,
               person_id, zone
        FROM events WHERE behavior='interested' {date_clause}
        GROUP BY t, person_id ORDER BY timestamp LIMIT 20
    """)

    # AI Insight
    try:
        from ai_insight import get_ai_insight, insight_to_html as _i2h
        import os as _os
        _api = _os.environ.get("ANTHROPIC_API_KEY","")
        _res = get_ai_insight(db_path, date_filter, api_key=_api)
        insight_html = _i2h(_res.get("insight") or _res.get("fallback",""))
        insight_src  = "AI Analysis (Claude Haiku)" if _res.get("ok") else "Automated Analysis"
    except Exception as _e:
        insight_html = f"<p>Analysis unavailable: {_e}</p>"
        insight_src  = "Analysis unavailable"

    conn.close()

    # Build JSON for charts
    hours = sorted(set(r[0] for r in hourly_persons))
    hp_map = {r[0]: r[1] for r in hourly_persons}
    hourly_persons_data = [hp_map.get(h, 0) for h in hours]
    hour_labels = [f"{h}:00" for h in hours]

    behaviors = [r[0] for r in behavior_totals]
    behavior_counts = [r[1] for r in behavior_totals]
    BEHAVIOR_COLORS_MAP = {
        "browsing":     "#818cf8",
        "interested":   "#fbbf24",
        "moving":       "#6b7280",
        "queuing":      "#34d399",
        "purchasing":   "#10b981",
        "being_served": "#6ee7b7",
        "accompanied":  "#a3e635",
        "seated":       "#fb923c",
        "waiting":      "#f87171",
        "entering":     "#38bdf8",
        "staff":        "#c084fc",
    }
    behavior_colors = [BEHAVIOR_COLORS_MAP.get(b, "#888") for b in behaviors]

    # stacked datasets
    all_behaviors = list(dict.fromkeys(r[1] for r in hourly_behavior))
    stacked_datasets = []
    for beh in all_behaviors:
        bmap = {r[0]: r[2] for r in hourly_behavior if r[1] == beh}
        stacked_datasets.append({
            "label": beh.capitalize(),
            "data": [bmap.get(h, 0) for h in hours],
            "backgroundColor": BEHAVIOR_COLORS_MAP.get(beh, "#888"),
            "borderRadius": 4,
            "borderSkipped": False,
        })

    # zone bars
    max_zone = zone_activity[0][1] if zone_activity else 1
    zone_bars_html = ""
    zone_colors = {
        "wine_left": "#34d399", "wine_right": "#34d399", "wine_back": "#34d399",
        "counter": "#f472b6", "staff_area_1": "#c084fc", "seating": "#fb923c",
        "entrance": "#38bdf8",
    }
    for zname, zcount in zone_activity:
        pct = int(zcount / max_zone * 100)
        col = zone_colors.get(zname, "#818cf8")
        zone_bars_html += f"""
        <div class="zone-row">
          <div class="zone-meta">
            <span class="zone-name">{zname}</span>
            <span class="zone-count">{zcount:,} events</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" style="width:{pct}%;background:{col};"></div></div>
        </div>"""

    # interested timeline html
    tl_html = ""
    for t, pid, zone in interested_tl:
        tl_html += f"""
        <div class="tl-item">
          <div class="tl-dot" style="background:#fbbf24;"></div>
          <span class="tl-time">{t}</span>
          <span class="tl-zone">Person #{pid} &nbsp;&rarr;&nbsp; {zone}</span>
          <span class="tl-badge" style="background:#2d2010;color:#fbbf24;">interested</span>
        </div>"""

    if not tl_html:
        tl_html = '<p style="color:#6a6880;font-size:13px;">No interested events recorded</p>'

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Wine O'Clock — Behavior Report {report_date}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#0f0f13;color:#e8e6e0;min-height:100vh}}
header{{background:linear-gradient(135deg,#1a0a2e,#2d1a4a);border-bottom:1px solid #4a2d6e;padding:28px 40px;display:flex;align-items:center;gap:20px}}
.logo{{font-size:32px}}.date-badge{{margin-left:auto;background:#2d1a4a;border:1px solid #6a3d9a;border-radius:20px;padding:6px 16px;font-size:13px;color:#c4a8f0}}
header h1{{font-size:22px;font-weight:600;color:#e8d5ff}}header p{{font-size:13px;color:#9a80c0;margin-top:4px}}
main{{max-width:1200px;margin:0 auto;padding:32px 24px}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:32px}}
.kpi{{background:#1a1a24;border:1px solid #2a2a3a;border-radius:14px;padding:20px 22px;display:flex;flex-direction:column;gap:6px}}
.kpi-label{{font-size:12px;color:#7a7890;text-transform:uppercase;letter-spacing:.5px}}
.kpi-value{{font-size:36px;font-weight:700}}.kpi-sub{{font-size:12px;color:#7a7890}}
.kpi.purple .kpi-value{{color:#c084fc}}.kpi.amber .kpi-value{{color:#fbbf24}}
.kpi.green .kpi-value{{color:#34d399}}.kpi.red .kpi-value{{color:#f87171}}
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}}
.charts-row.single{{grid-template-columns:1fr}}
.card{{background:#1a1a24;border:1px solid #2a2a3a;border-radius:14px;padding:24px}}
.card h2{{font-size:15px;font-weight:600;color:#d4c8f0;margin-bottom:4px}}
.card p{{font-size:12px;color:#6a6880;margin-bottom:20px}}
.chart-wrap{{position:relative;height:260px}}.chart-wrap.tall{{height:300px}}
.timeline{{display:flex;flex-direction:column;gap:10px}}
.tl-item{{display:flex;align-items:center;gap:14px;background:#22213a;border-radius:10px;padding:12px 16px}}
.tl-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.tl-time{{font-size:13px;color:#9a8ab0;min-width:52px}}
.tl-zone{{font-size:13px;color:#e0d0ff}}
.tl-badge{{margin-left:auto;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px}}
.zone-bars{{display:flex;flex-direction:column;gap:14px}}
.zone-row{{display:flex;flex-direction:column;gap:6px}}
.zone-meta{{display:flex;justify-content:space-between;font-size:13px}}
.zone-name{{color:#c4b8e0}}.zone-count{{color:#7a7890}}
.bar-bg{{background:#2a2a3a;border-radius:6px;height:10px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:6px;transition:width .6s ease}}
footer{{text-align:center;padding:24px;font-size:12px;color:#4a4860;border-top:1px solid #1e1e2a;margin-top:8px}}
.insight-box{{background:#1a1a28;border:1px solid #3a2a4a;border-radius:14px;padding:24px;margin-bottom:20px}}
.insight-box h2{{font-size:15px;font-weight:600;color:#d4c8f0;margin-bottom:4px}}
.insight-src{{font-size:11px;color:#6a5880;margin-bottom:16px}}
.insight-section-title{{font-size:13px;font-weight:700;color:#c084fc;margin:14px 0 5px}}
.insight-p{{font-size:13px;color:#c8c0e0;line-height:1.6;margin:2px 0}}
.insight-rec{{background:#22213a;border-left:3px solid #7c3aed;border-radius:6px;
  padding:8px 14px;margin:4px 0;font-size:13px;color:#d4c8f0}}
</style>
</head>
<body>
<header>
  <div class="logo">🍷</div>
  <div>
    <h1>Wine O'Clock Khonkaen — Customer Behavior Report</h1>
    <p>วันที่ {report_date} &nbsp;|&nbsp; {time_start} – {time_end} น.</p>
  </div>
  <div class="date-badge">{report_date}</div>
</header>
<main>
  <div class="kpi-row">
    <div class="kpi purple">
      <span class="kpi-label">ลูกค้าทั้งหมด</span>
      <span class="kpi-value">{total_persons}</span>
      <span class="kpi-sub">unique persons detected</span>
    </div>
    <div class="kpi amber">
      <span class="kpi-label">หยุดดูไวน์ (Interested)</span>
      <span class="kpi-value">{interested_persons}</span>
      <span class="kpi-sub">persons detected</span>
    </div>
    <div class="kpi green">
      <span class="kpi-label">เข้า Counter</span>
      <span class="kpi-value">{purchasing_persons}</span>
      <span class="kpi-sub">persons at counter</span>
    </div>
    <div class="kpi red">
      <span class="kpi-label">Zone ยอดนิยม</span>
      <span class="kpi-value" style="font-size:20px;margin-top:6px;">{top_zone_name}</span>
      <span class="kpi-sub">most visited zone</span>
    </div>
  </div>

  <div class="charts-row">
    <div class="card">
      <h2>จำนวนลูกค้าแต่ละชั่วโมง</h2>
      <p>Unique persons detected per hour</p>
      <div class="chart-wrap"><canvas id="hourlyChart"></canvas></div>
    </div>
    <div class="card">
      <h2>สัดส่วนพฤติกรรมทั้งหมด</h2>
      <p>Distribution of all behavior events</p>
      <div class="chart-wrap"><canvas id="behaviorDonut"></canvas></div>
    </div>
  </div>

  <div class="charts-row">
    <div class="card">
      <h2>กิจกรรมในแต่ละ Zone</h2>
      <p>Event count by zone (excluding floor)</p>
      <div class="zone-bars" style="margin-top:8px;">{zone_bars_html}</div>
    </div>
    <div class="card">
      <h2>Timeline ลูกค้าที่หยุดดูไวน์</h2>
      <p>เวลาที่ลูกค้าหยุดนาน > 20s — ควรส่งพนักงานไปแนะนำ</p>
      <div class="timeline">{tl_html}</div>
    </div>
  </div>

  <div class="charts-row single">
    <div class="card">
      <h2>พฤติกรรมรายชั่วโมง</h2>
      <p>Behavior events breakdown by hour</p>
      <div class="chart-wrap tall"><canvas id="stackedChart"></canvas></div>
    </div>
  </div>
  <div style="max-width:1200px;margin:0 auto;padding:0 24px 20px">
    <div class="insight-box">
      <h2>🤖 Daily Insight &amp; Recommendations</h2>
      <div class="insight-src">{insight_src}</div>
      {insight_html}
    </div>
  </div>
</main>
<footer>Wine AI — Customer Behavior System &nbsp;|&nbsp; {db_path} &nbsp;|&nbsp; Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</footer>

<script>
Chart.defaults.color='#7a7890';
Chart.defaults.borderColor='#2a2a3a';
Chart.defaults.font.family='Segoe UI,sans-serif';

new Chart(document.getElementById('hourlyChart'),{{
  type:'bar',
  data:{{labels:{json.dumps(hour_labels)},datasets:[{{label:'Unique persons',data:{json.dumps(hourly_persons_data)},backgroundColor:'#7c3aed',borderRadius:8,borderSkipped:false}}]}},
  options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,ticks:{{stepSize:1}},grid:{{color:'#1e1e2a'}}}},x:{{grid:{{display:false}}}}}}}}
}});

new Chart(document.getElementById('behaviorDonut'),{{
  type:'doughnut',
  data:{{labels:{json.dumps([b.capitalize() for b in behaviors])},datasets:[{{data:{json.dumps(behavior_counts)},backgroundColor:{json.dumps(behavior_colors)},borderWidth:0,hoverOffset:8}}]}},
  options:{{responsive:true,maintainAspectRatio:false,cutout:'65%',plugins:{{legend:{{position:'right',labels:{{padding:16,usePointStyle:true,pointStyleWidth:10}}}},tooltip:{{callbacks:{{label:ctx=>{{const t=ctx.dataset.data.reduce((a,b)=>a+b,0);return ` ${{ctx.label}}: ${{ctx.parsed.toLocaleString()}} (${{((ctx.parsed/t)*100).toFixed(1)}}%)`}}}}}}}}}}
}});

new Chart(document.getElementById('stackedChart'),{{
  type:'bar',
  data:{{labels:{json.dumps(hour_labels)},datasets:{json.dumps(stacked_datasets)}}},
  options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top',labels:{{usePointStyle:true,padding:20}}}},tooltip:{{mode:'index'}}}},scales:{{x:{{stacked:true,grid:{{display:false}}}},y:{{stacked:true,grid:{{color:'#1e1e2a'}}}}}}}}
}});
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",   default="behavior_log.db")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--out",  default=None)
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}")
        sys.exit(1)

    html     = build_report(args.db, args.date)
    out_path = args.out or f"report_{args.date or 'all'}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Report saved: {out_path}")
    print(f"Open in browser: file:///{Path(out_path).resolve()}")


if __name__ == "__main__":
    main()
