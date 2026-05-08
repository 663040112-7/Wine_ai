# =============================================================================
# data_manager.py — Data Security & Privacy Management
# features:
#   - Auto-delete events older than N days (default 30)
#   - Summary stats before deletion (audit trail)
#   - No images stored — behavior events only
#   - PDPA-friendly: no personal identifiers stored
# =============================================================================
import sqlite3
import os
from datetime import datetime, timedelta


class DataManager:
    RETENTION_DAYS = 30   # เก็บข้อมูลไว้กี่วัน

    def __init__(self, db_path: str = "behavior_log.db"):
        self.db_path = db_path

    def get_stats(self) -> dict:
        """สรุปข้อมูลที่มีอยู่ใน db"""
        if not os.path.exists(self.db_path):
            return {"error": "DB not found"}

        conn = sqlite3.connect(self.db_path)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM events").fetchone()[0]
            oldest = conn.execute(
                "SELECT MIN(datetime(timestamp,'unixepoch','+7 hours'))"
                " FROM events").fetchone()[0]
            newest = conn.execute(
                "SELECT MAX(datetime(timestamp,'unixepoch','+7 hours'))"
                " FROM events").fetchone()[0]
            by_date = conn.execute("""
                SELECT date(datetime(timestamp,'unixepoch','+7 hours')) as d,
                       COUNT(*) as n
                FROM events GROUP BY d ORDER BY d DESC LIMIT 10
            """).fetchall()
        finally:
            conn.close()

        return {
            "total_events": total,
            "oldest": oldest,
            "newest": newest,
            "by_date": by_date,
        }

    def delete_old_data(self, days: int = None, dry_run: bool = False) -> int:
        """
        ลบข้อมูลที่เก่ากว่า N วัน
        dry_run=True → แค่นับ ไม่ลบจริง
        คืนจำนวน records ที่ลบ
        """
        if not os.path.exists(self.db_path):
            print("DB not found")
            return 0

        days      = days or self.RETENTION_DAYS
        cutoff_dt = datetime.now() - timedelta(days=days)
        cutoff_ts = cutoff_dt.timestamp()

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp < ?",
                (cutoff_ts,)
            ).fetchone()[0]

            if dry_run:
                print(f"[DryRun] would delete {count} events "
                      f"older than {days} days (before {cutoff_dt.date()})")
                return count

            if count > 0:
                conn.execute(
                    "DELETE FROM events WHERE timestamp < ?", (cutoff_ts,))
                conn.execute("VACUUM")   # reclaim disk space
                conn.commit()
                print(f"[DataManager] deleted {count} events "
                      f"older than {days} days")
            else:
                print(f"[DataManager] no events older than {days} days")

            return count
        finally:
            conn.close()

    def run_daily_cleanup(self):
        """เรียกตอนเริ่ม main.py ทุกวัน — ลบอัตโนมัติ"""
        stats = self.get_stats()
        print(f"[DataManager] DB: {stats.get('total_events', 0)} events  "
              f"({stats.get('oldest', 'N/A')} → {stats.get('newest', 'N/A')})")
        self.delete_old_data()

    def export_summary(self, output_path: str = "data_summary.txt"):
        """
        Export สรุปข้อมูลแบบ anonymized (ไม่มี person_id)
        ใช้แสดงให้ audit โดยไม่เปิดเผยข้อมูลส่วนบุคคล
        """
        if not os.path.exists(self.db_path):
            print("DB not found")
            return

        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute("""
                SELECT 
                    date(datetime(timestamp,'unixepoch','+7 hours')) as date,
                    cam_key,
                    zone,
                    behavior,
                    COUNT(*) as events,
                    SUM(needs_staff) as alerts
                FROM events
                GROUP BY date, cam_key, zone, behavior
                ORDER BY date DESC, events DESC
            """).fetchall()
        finally:
            conn.close()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("Wine O'Clock — Behavior Data Summary\n")
            f.write(f"Generated: {datetime.now()}\n")
            f.write(f"Retention: {self.RETENTION_DAYS} days\n")
            f.write("Note: No personal identifiers stored\n")
            f.write("="*60 + "\n\n")
            f.write(f"{'Date':<12} {'Cam':<8} {'Zone':<20} "
                    f"{'Behavior':<15} {'Events':>8} {'Alerts':>8}\n")
            f.write("-"*75 + "\n")
            for r in rows:
                f.write(f"{r[0]:<12} {r[1]:<8} {r[2]:<20} "
                        f"{r[3]:<15} {r[4]:>8} {r[5]:>8}\n")

        print(f"[DataManager] summary exported → {output_path}")


# ── CLI usage ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    dm = DataManager()

    if "--stats" in sys.argv:
        s = dm.get_stats()
        print(f"Total events : {s.get('total_events', 0)}")
        print(f"Oldest       : {s.get('oldest', 'N/A')}")
        print(f"Newest       : {s.get('newest', 'N/A')}")
        print("\nRecent days:")
        for d, n in s.get("by_date", []):
            print(f"  {d}: {n:,} events")

    elif "--cleanup" in sys.argv:
        days = int(sys.argv[sys.argv.index("--cleanup") + 1]) \
               if "--cleanup" in sys.argv and \
               sys.argv.index("--cleanup") + 1 < len(sys.argv) and \
               sys.argv[sys.argv.index("--cleanup") + 1].isdigit() \
               else DataManager.RETENTION_DAYS
        dm.delete_old_data(days=days)

    elif "--dry-run" in sys.argv:
        dm.delete_old_data(dry_run=True)

    elif "--export" in sys.argv:
        dm.export_summary()

    else:
        print("Usage:")
        print("  python data_manager.py --stats          # ดูสรุปข้อมูล")
        print("  python data_manager.py --dry-run        # ดูว่าจะลบอะไรบ้าง")
        print("  python data_manager.py --cleanup 30     # ลบข้อมูลเกิน 30 วัน")
        print("  python data_manager.py --export         # export summary")
