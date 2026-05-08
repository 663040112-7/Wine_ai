# =============================================================================
# report_pdf.py — Wine AI Professional PDF Report
# =============================================================================
import sqlite3, argparse, os
from datetime import datetime
from pathlib import Path
from ai_insight import get_ai_insight, insight_to_html

TZ = 7

def query(conn, sql, p=()):
    return conn.execute(sql, p).fetchall()

def build_pdf(db_path: str, date_filter: str = None, out_path: str = None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
    from reportlab.pdfgen import canvas as pdfcanvas

    conn = sqlite3.connect(db_path)
    dc   = f"date(datetime(timestamp,'unixepoch','+{TZ} hours'))"
    wh   = f"AND {dc}=?" if date_filter else ""
    p    = (date_filter,) if date_filter else ()

    total  = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE 1=1 {wh}", p)[0][0]
    inter  = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='interested' {wh}", p)[0][0]
    purch  = query(conn, f"SELECT COUNT(DISTINCT person_id) FROM events WHERE behavior='purchasing' {wh}", p)[0][0]
    alrt   = query(conn, f"SELECT COUNT(*) FROM events WHERE needs_staff=1 {wh}", p)[0][0]
    top_z  = query(conn, f"SELECT zone,COUNT(*) n FROM events WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 1", p)
    dr     = query(conn, f"""SELECT MIN(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
                                    MAX(strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours'))),
                                    {dc} FROM events WHERE 1=1 {wh}""", p)[0]
    hourly = query(conn, f"""SELECT strftime('%H',datetime(timestamp,'unixepoch','+{TZ} hours')) hr,
                                    COUNT(DISTINCT person_id) n FROM events WHERE 1=1 {wh}
                             GROUP BY hr ORDER BY hr""", p)
    behs   = query(conn, f"SELECT behavior,COUNT(*) n FROM events WHERE 1=1 {wh} GROUP BY behavior ORDER BY n DESC", p)
    zones  = query(conn, f"SELECT zone,COUNT(*) n FROM events WHERE zone!='floor' {wh} GROUP BY zone ORDER BY n DESC LIMIT 8", p)
    tl     = query(conn, f"""SELECT strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')),
                                    person_id, zone, behavior FROM events
                             WHERE needs_staff=1 {wh}
                             GROUP BY strftime('%H:%M',datetime(timestamp,'unixepoch','+{TZ} hours')), person_id
                             ORDER BY timestamp DESC LIMIT 20""", p)
    conn.close()

    rep_date = dr[2] or date_filter or datetime.now().strftime("%Y-%m-%d")
    t_start, t_end = dr[0] or "—", dr[1] or "—"
    if not out_path:
        out_path = f"report_{rep_date}.pdf"

    # ── Colors ────────────────────────────────────────────────────────────────
    WINE   = colors.HexColor("#6B2737")
    WINE_L = colors.HexColor("#8B3A4C")
    WINE_BG= colors.HexColor("#FDF5F6")
    DARK   = colors.HexColor("#1A1A2E")
    GRAY   = colors.HexColor("#5A5A72")
    LGRAY  = colors.HexColor("#F4F4F8")
    MGRAY  = colors.HexColor("#E8E8F0")
    GREEN  = colors.HexColor("#1B5E20")
    GREEN_L= colors.HexColor("#E8F5E9")
    AMBER  = colors.HexColor("#E65100")
    AMBER_L= colors.HexColor("#FFF8E1")
    RED    = colors.HexColor("#B71C1C")
    RED_L  = colors.HexColor("#FFEBEE")
    BLUE   = colors.HexColor("#0D47A1")
    BLUE_L = colors.HexColor("#E3F2FD")
    WHITE  = colors.white
    BLACK  = colors.black

    PAGE_W, PAGE_H = A4
    ML = MR = 1.8*cm
    MT = 2.0*cm
    MB = 1.8*cm
    CW = PAGE_W - ML - MR   # content width

    # ── Page template with header/footer ──────────────────────────────────────
    class WineDocTemplate(BaseDocTemplate):
        def __init__(self, filename, **kw):
            super().__init__(filename, **kw)
            frame = Frame(ML, MB+1.2*cm, CW, PAGE_H-MT-MB-1.2*cm, id='main')
            self.addPageTemplates([PageTemplate(id='main', frames=frame,
                                                onPage=self._draw_chrome)])
            self.page_num = 0

        def _draw_chrome(self, cvs, doc):
            cvs.saveState()
            # Header bar
            cvs.setFillColor(WINE)
            cvs.rect(0, PAGE_H-1.4*cm, PAGE_W, 1.4*cm, fill=1, stroke=0)
            cvs.setFillColor(WHITE)
            cvs.setFont("Helvetica-Bold", 10)
            cvs.drawString(ML, PAGE_H-0.9*cm, "🍷  Wine O'Clock Khonkaen — Customer Behavior Report")
            cvs.setFont("Helvetica", 9)
            cvs.drawRightString(PAGE_W-MR, PAGE_H-0.9*cm, f"Date: {rep_date}")
            # Footer bar
            cvs.setFillColor(MGRAY)
            cvs.rect(0, 0, PAGE_W, 1.1*cm, fill=1, stroke=0)
            cvs.setFillColor(GRAY)
            cvs.setFont("Helvetica", 8)
            cvs.drawString(ML, 0.38*cm, "Wine AI Customer Behavior Detection System  |  Confidential")
            cvs.setFont("Helvetica-Bold", 9)
            cvs.drawRightString(PAGE_W-MR, 0.38*cm, f"Page {doc.page}")
            cvs.restoreState()

    # ── Styles ────────────────────────────────────────────────────────────────
    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    T_COVER   = S("cover",   fontName="Helvetica-Bold", fontSize=28, textColor=WHITE,  alignment=TA_CENTER, leading=34)
    T_SUB     = S("sub",     fontName="Helvetica",      fontSize=11, textColor=WHITE,  alignment=TA_CENTER, leading=16)
    T_SECTION = S("sec",     fontName="Helvetica-Bold", fontSize=13, textColor=WHITE,  spaceAfter=0)
    T_BODY    = S("body",    fontName="Helvetica",      fontSize=9.5, textColor=DARK,   leading=14, spaceAfter=4)
    T_LABEL   = S("lbl",     fontName="Helvetica-Bold", fontSize=8,  textColor=GRAY,   leading=12)
    T_NOTE    = S("note",    fontName="Helvetica-Oblique", fontSize=8, textColor=GRAY, leading=12, spaceAfter=4)

    # ── Builder helpers ───────────────────────────────────────────────────────
    story = []

    def section_header(title, subtitle=""):
        tbl_data = [[Paragraph(title, T_SECTION)]]
        t = Table(tbl_data, colWidths=[CW])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), WINE),
            ("TOPPADDING",  (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",(0,0),(-1,-1), 10),
            ("LEFTPADDING", (0,0), (-1,-1), 14),
            ("RIGHTPADDING",(0,0), (-1,-1), 14),
            ("BOX",         (0,0), (-1,-1), 0, WHITE),
        ]))
        story.append(t)
        if subtitle:
            story.append(Paragraph(subtitle, T_NOTE))
        story.append(Spacer(1, 6))

    def kpi_cards(items):
        # items = [(value, label, bg_color, text_color), ...]
        n = len(items)
        col_w = CW / n
        vals  = [[Paragraph(f"<b>{v}</b>", S("v", fontName="Helvetica-Bold",
                    fontSize=28, textColor=tc, alignment=TA_CENTER)) for v,l,bg,tc in items]]
        lbls  = [[Paragraph(l, S("l", fontName="Helvetica", fontSize=8,
                    textColor=GRAY, alignment=TA_CENTER)) for v,l,bg,tc in items]]
        bgs   = [bg for v,l,bg,tc in items]

        row_v = TableStyle([("TOPPADDING",(0,0),(-1,-1),16),("BOTTOMPADDING",(0,0),(-1,-1),4)] +
                           [(f"BACKGROUND",(i,0),(i,0),bgs[i]) for i in range(n)])
        row_l = TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),14)] +
                           [(f"BACKGROUND",(i,0),(i,0),bgs[i]) for i in range(n)])

        tv = Table(vals, colWidths=[col_w]*n)
        tv.setStyle(row_v)
        tl_ = Table(lbls, colWidths=[col_w]*n)
        tl_.setStyle(row_l)

        # outer card border
        outer = Table([[tv],[tl_]], colWidths=[CW])
        outer.setStyle(TableStyle([
            ("BOX",         (0,0),(-1,-1), 1, MGRAY),
            ("LINEABOVE",   (0,1),(-1,1),  0.5, MGRAY),
            ("TOPPADDING",  (0,0),(-1,-1), 0),
            ("BOTTOMPADDING",(0,0),(-1,-1),0),
            ("LEFTPADDING", (0,0),(-1,-1), 0),
            ("RIGHTPADDING",(0,0),(-1,-1), 0),
        ]))
        story.append(outer)
        story.append(Spacer(1, 10))

    def pro_table(headers, rows, col_widths, col_aligns=None):
        data = [headers] + rows
        ts   = TableStyle([
            # Header
            ("BACKGROUND",    (0,0), (-1,0),  DARK),
            ("TEXTCOLOR",     (0,0), (-1,0),  WHITE),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,0),  8.5),
            ("TOPPADDING",    (0,0), (-1,0),  8),
            ("BOTTOMPADDING", (0,0), (-1,0),  8),
            ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
            # Body
            ("FONTNAME",      (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",      (0,1), (-1,-1), 8.5),
            ("TEXTCOLOR",     (0,1), (-1,-1), DARK),
            ("TOPPADDING",    (0,1), (-1,-1), 6),
            ("BOTTOMPADDING", (0,1), (-1,-1), 6),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, LGRAY]),
            ("GRID",          (0,0), (-1,-1), 0.3, MGRAY),
            ("BOX",           (0,0), (-1,-1), 0.8, colors.HexColor("#CCCCCC")),
            ("ALIGN",         (0,0), (-1,0),  "CENTER"),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ])
        if col_aligns:
            for col_idx, align in enumerate(col_aligns):
                if align != "LEFT":
                    ts.add("ALIGN", (col_idx,1), (col_idx,-1), align)
        t = Table(data, colWidths=col_widths)
        t.setStyle(ts)
        story.append(t)
        story.append(Spacer(1, 10))

    def bar_cell(value, max_val, color="#6B2737"):
        if hasattr(color, 'hexval'):
            color = "#" + color.hexval()[2:]
        pct = min(value / max_val, 1.0) if max_val > 0 else 0
        bar_w = int(pct * 20)
        filled = "█" * bar_w
        empty  = "░" * (20 - bar_w)
        return Paragraph(f'<font color="{color}"><b>{filled}</b></font>'
                         f'<font color="#CCCCCC">{empty}</font>',
                         S("bar", fontName="Helvetica", fontSize=8, textColor=DARK))

    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE 1 — COVER
    # ═══════════════════════════════════════════════════════════════════════════
    # Full-width cover block
    cover_data = [[
        Paragraph("WINE O'CLOCK KHONKAEN", T_COVER),
        ],[
        Paragraph("Customer Behavior Analysis Report", T_SUB),
        ],[
        Paragraph(f"Reporting Period: {rep_date}  &nbsp;·&nbsp;  {t_start} – {t_end}", T_SUB),
        ],[
        Paragraph(f"Generated: {datetime.now().strftime('%d %B %Y, %H:%M')}", T_SUB),
    ]]
    cv = Table(cover_data, colWidths=[CW])
    cv.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), WINE),
        ("TOPPADDING",    (0,0), (0,0),   36),
        ("BOTTOMPADDING", (0,0), (0,0),   8),
        ("TOPPADDING",    (0,1), (0,1),   4),
        ("BOTTOMPADDING", (0,1), (0,1),   4),
        ("TOPPADDING",    (0,2), (0,2),   4),
        ("BOTTOMPADDING", (0,2), (0,2),   4),
        ("TOPPADDING",    (0,3), (0,3),   8),
        ("BOTTOMPADDING", (0,3), (0,3),   36),
        ("LEFTPADDING",   (0,0), (-1,-1), 20),
        ("RIGHTPADDING",  (0,0), (-1,-1), 20),
    ]))
    story.append(cv)
    story.append(Spacer(1, 20))

    # Summary info box
    info_data = [
        [Paragraph("<b>Report Period</b>",   S("k", fontName="Helvetica-Bold", fontSize=9, textColor=GRAY)),
         Paragraph(rep_date,                 S("v", fontName="Helvetica",      fontSize=9, textColor=DARK))],
        [Paragraph("<b>Operating Hours</b>", S("k", fontName="Helvetica-Bold", fontSize=9, textColor=GRAY)),
         Paragraph(f"{t_start} – {t_end}",  S("v", fontName="Helvetica",      fontSize=9, textColor=DARK))],
        [Paragraph("<b>Data Source</b>",     S("k", fontName="Helvetica-Bold", fontSize=9, textColor=GRAY)),
         Paragraph(db_path,                  S("v", fontName="Helvetica",      fontSize=9, textColor=DARK))],
        [Paragraph("<b>System Version</b>",  S("k", fontName="Helvetica-Bold", fontSize=9, textColor=GRAY)),
         Paragraph("Wine AI v2.0",           S("v", fontName="Helvetica",      fontSize=9, textColor=DARK))],
    ]
    it = Table(info_data, colWidths=[CW*0.3, CW*0.7])
    it.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), WINE_BG),
        ("BOX",           (0,0), (-1,-1), 1, colors.HexColor("#DDB8C0")),
        ("INNERGRID",     (0,0), (-1,-1), 0.3, colors.HexColor("#EED0D6")),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(it)
    story.append(Spacer(1, 20))

    # ═══════════════════════════════════════════════════════════════════════════
    # PAGE 2 — KEY METRICS
    # ═══════════════════════════════════════════════════════════════════════════
    section_header("KEY PERFORMANCE INDICATORS", "Summary of customer activity for the reporting period")
    kpi_cards([
        (str(total), "TOTAL CUSTOMERS",  BLUE_L,  BLUE),
        (str(inter),  "INTERESTED IN WINE", AMBER_L, AMBER),
        (str(purch),  "REACHED COUNTER",  GREEN_L, GREEN),
        (str(alrt),   "STAFF ALERTS",      RED_L,   RED),
        (top_z[0][0] if top_z else "N/A", "TOP ZONE", WINE_BG, WINE),
    ])

    # Insight paragraph
    if total > 0:
        conv = round(inter/total*100, 1) if total else 0
        story.append(Paragraph(
            f"<b>Insight:</b> Out of <b>{total}</b> customers detected today, "
            f"<b>{inter}</b> ({conv}%) showed interest in wine products. "
            f"<b>{purch}</b> proceeded to the checkout counter. "
            f"A total of <b>{alrt}</b> staff alerts were generated.",
            S("ins", fontName="Helvetica", fontSize=9, textColor=DARK,
              backColor=LGRAY, borderPadding=8, leading=14, spaceAfter=10)
        ))
    story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════════════════
    # HOURLY TRAFFIC
    # ═══════════════════════════════════════════════════════════════════════════
    section_header("HOURLY CUSTOMER TRAFFIC", "Unique customers detected per hour")
    if hourly:
        max_h = max(r[1] for r in hourly) or 1
        peak_hr = max(hourly, key=lambda r: r[1])
        rows = []
        for hr_val, cnt in hourly:
            pct   = cnt/max_h*100
            is_pk = hr_val == peak_hr[0]
            rows.append([
                Paragraph(f"<b>{hr_val}:00</b>" if is_pk else f"{hr_val}:00",
                          S("h", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                            fontSize=9, textColor=WINE if is_pk else DARK, alignment=TA_CENTER)),
                Paragraph(f"<b>{cnt}</b>" if is_pk else str(cnt),
                          S("c", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                            fontSize=9, textColor=WINE if is_pk else DARK, alignment=TA_CENTER)),
                bar_cell(cnt, max_h, "#6B2737"),
                Paragraph(f"{'▲ PEAK  ' if is_pk else ''}{pct:.0f}%",
                          S("p", fontName="Helvetica-Bold" if is_pk else "Helvetica",
                            fontSize=8, textColor=WINE if is_pk else GRAY, alignment=TA_RIGHT)),
            ])
        pro_table(["Hour","Customers","Traffic","% of Peak"],
                  rows, [CW*0.15, CW*0.15, CW*0.5, CW*0.2])
        story.append(Paragraph(
            f"<b>Peak hour:</b> {peak_hr[0]}:00 with {peak_hr[1]} unique customers detected.",
            T_NOTE))
    else:
        story.append(Paragraph("No hourly data available for this period.", T_NOTE))
    story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════════════════
    # BEHAVIOR BREAKDOWN
    # ═══════════════════════════════════════════════════════════════════════════
    section_header("BEHAVIOR BREAKDOWN", "Distribution of customer behavior events")
    ALERT_SET = {"interested","loitering","purchasing","waiting"}
    BEH_COLORS = {
        "wine_browsing":"#B8860B","interested":"#E65100","loitering":"#B71C1C",
        "purchasing":"#1B5E20","processing":"#006064","seated":"#BF360C",
        "waiting":"#880E4F","being_assisted":"#2E7D32","moving":"#5A5A72",
        "idle":"#3A3A52","bar_waiting":"#6A1B9A","seller":"#4A148C",
    }
    if behs:
        total_ev = sum(r[1] for r in behs) or 1
        rows = []
        for beh, cnt in behs:
            pct     = cnt/total_ev*100
            is_alrt = beh in ALERT_SET
            col     = BEH_COLORS.get(beh, "#666666")
            rows.append([
                Paragraph(f'<font color="{col}"><b>●</b></font> {beh.replace("_"," ").title()}',
                          S("beh", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"{cnt:,}",
                          S("cnt", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                bar_cell(cnt, total_ev, col),
                Paragraph(f"{pct:.1f}%",
                          S("pp", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                Paragraph("⚠ Alert" if is_alrt else "—",
                          S("al", fontName="Helvetica-Bold" if is_alrt else "Helvetica",
                            fontSize=8, textColor=RED if is_alrt else GRAY, alignment=TA_CENTER)),
            ])
        pro_table(["Behavior","Events","Distribution","Share","Alert Trigger"],
                  rows, [CW*0.28, CW*0.13, CW*0.32, CW*0.13, CW*0.14])
    story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════════════════
    # ZONE ACTIVITY
    # ═══════════════════════════════════════════════════════════════════════════
    section_header("ZONE ACTIVITY", "Event frequency by detection zone")
    ZONE_COLORS = {
        "wine_left":"#2E7D32","wine_right":"#2E7D32","wine_back":"#2E7D32",
        "counter_checkout":"#B71C1C","seller_zone":"#E65100",
        "seating":"#1565C0","counter_bar":"#6A1B9A","entrance":"#00695C",
    }
    if zones:
        max_z = zones[0][1] or 1
        tot_z = sum(r[1] for r in zones)
        rows  = []
        for i,(zn,cnt) in enumerate(zones):
            col = ZONE_COLORS.get(zn,"#5A5A72")
            rows.append([
                Paragraph(str(i+1),
                          S("rk", fontName="Helvetica-Bold", fontSize=10, textColor=WINE, alignment=TA_CENTER)),
                Paragraph(f'<font color="{col}"><b>■</b></font>  {zn}',
                          S("zn", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f"{cnt:,}",
                          S("zc", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                bar_cell(cnt, max_z, col),
                Paragraph(f"{cnt/tot_z*100:.1f}%",
                          S("zp", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
            ])
        pro_table(["Rank","Zone","Events","Activity","Share"],
                  rows, [CW*0.08, CW*0.28, CW*0.13, CW*0.35, CW*0.16])
    story.append(Spacer(1, 12))

    # ═══════════════════════════════════════════════════════════════════════════
    # ALERT TIMELINE
    # ═══════════════════════════════════════════════════════════════════════════
    section_header("STAFF ALERT TIMELINE", "Customers requiring staff assistance — chronological log")
    BEH_BG = {
        "loitering":  (RED,   RED_L),
        "interested": (AMBER, AMBER_L),
        "purchasing": (GREEN, GREEN_L),
        "waiting":    (RED,   RED_L),
    }
    if tl:
        rows = []
        for t_val, pid, zone, beh in tl:
            tc, bg = BEH_BG.get(beh, (GRAY, LGRAY))
            rows.append([
                Paragraph(t_val,
                          S("tt", fontName="Helvetica-Bold", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                Paragraph(f"#{pid}",
                          S("tp", fontName="Helvetica", fontSize=9, textColor=DARK, alignment=TA_CENTER)),
                Paragraph(zone,
                          S("tz", fontName="Helvetica", fontSize=9, textColor=DARK)),
                Paragraph(f'<font color="#{tc.hexval()[2:]}"><b>{beh.replace("_"," ").title()}</b></font>',
                          S("tb", fontName="Helvetica-Bold", fontSize=9, textColor=tc)),
            ])
        pro_table(["Time","Person","Zone","Alert Type"],
                  rows, [CW*0.15, CW*0.15, CW*0.35, CW*0.35])
    else:
        story.append(Paragraph("No staff alerts were recorded for this period.", T_NOTE))

    # ═══════════════════════════════════════════════════════════════════════════
    # AI INSIGHT
    # ═══════════════════════════════════════════════════════════════════════════
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    ai_result = get_ai_insight(db_path, date_filter, api_key=api_key)
    insight_text = ai_result.get("insight") or ai_result.get("fallback", "")
    insight_source = "AI Analysis (Claude)" if ai_result.get("ok") else "Automated Analysis"

    section_header("DAILY INSIGHT & RECOMMENDATIONS", insight_source)

    # แปลง insight text เป็น paragraphs
    for line in insight_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if line.startswith("**") and line.endswith("**"):
            title = line.strip("*")
            story.append(Paragraph(title,
                S("it", fontName="Helvetica-Bold", fontSize=10.5,
                  textColor=WINE, spaceBefore=10, spaceAfter=3)))
        elif line[0:2].rstrip(".").isdigit():
            story.append(Paragraph(f"  {line}",
                S("ir", fontName="Helvetica", fontSize=9.5,
                  textColor=DARK, leading=14, spaceAfter=3,
                  leftIndent=12,
                  backColor=LGRAY, borderPadding=5)))
        else:
            clean = line.replace("**","")
            story.append(Paragraph(clean,
                S("ip", fontName="Helvetica", fontSize=9.5,
                  textColor=DARK, leading=14, spaceAfter=2)))

    story.append(Spacer(1, 12))

    # ── Footer note ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width=CW, color=MGRAY, thickness=0.5))
    story.append(Paragraph(
        f"This report was automatically generated by Wine AI System on "
        f"{datetime.now().strftime('%d %B %Y at %H:%M')}. "
        f"Data source: {os.path.basename(db_path)}. "
        f"All data is anonymized and retained for 30 days per PDPA policy.",
        S("disc", fontName="Helvetica-Oblique", fontSize=7.5, textColor=GRAY,
          alignment=TA_CENTER, spaceBefore=6, leading=12)
    ))

    # ── Build ──────────────────────────────────────────────────────────────────
    doc = WineDocTemplate(out_path, pagesize=A4,
                          leftMargin=ML, rightMargin=MR,
                          topMargin=MT, bottomMargin=MB+1.2*cm)
    doc.build(story)
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",   default="behavior_log.db")
    parser.add_argument("--date", default=None)
    parser.add_argument("--out",  default=None)
    args = parser.parse_args()
    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}")
        exit(1)
    out = build_pdf(args.db, args.date, args.out)
    print(f"Saved: {out}")
