"""Read-only: valores reais de status e presenca de external_id."""
import sqlite3

c = sqlite3.connect(r"C:\atlas-os\atlas_local.db")
print("status distintos em publications:")
for s, n in c.execute(
    "SELECT status, COUNT(*) FROM publications GROUP BY status ORDER BY 2 DESC"
).fetchall():
    print(f"  {str(s):20} {n}")
print("\ncom external_id NOT NULL:",
      c.execute("SELECT COUNT(*) FROM publications "
                "WHERE external_id IS NOT NULL").fetchone()[0])
print("por plataforma (external_id NOT NULL):")
for p, n in c.execute(
    "SELECT platform, COUNT(*) FROM publications "
    "WHERE external_id IS NOT NULL GROUP BY platform ORDER BY 2 DESC"
).fetchall():
    print(f"  {str(p):12} {n}")
print("\nvideo_metrics: janela temporal e distintos")
row = c.execute(
    "SELECT MIN(captured_at), MAX(captured_at), "
    "COUNT(DISTINCT video_asset_id||'|'||platform) FROM video_metrics"
).fetchone()
print("  primeiro:", row[0])
print("  ultimo:  ", row[1])
print("  pares (video,plataforma) distintos:", row[2])
print("  total linhas:",
      c.execute("SELECT COUNT(*) FROM video_metrics").fetchone()[0])
c.close()
