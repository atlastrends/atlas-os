"""Read-only: quantos posts publicados geram chamada externa por coleta."""
import sqlite3

c = sqlite3.connect(r"C:\atlas-os\atlas_local.db")
print("PUBLICADAS com external_id por plataforma "
      "(≈1 chamada externa cada por coleta):")
rows = c.execute(
    "SELECT platform, COUNT(*) FROM publications "
    "WHERE status='published' AND external_id IS NOT NULL "
    "GROUP BY platform ORDER BY 2 DESC"
).fetchall()
for p, n in rows:
    print(f"  {p:12} {n}")
total = c.execute(
    "SELECT COUNT(*) FROM publications "
    "WHERE status='published' AND external_id IS NOT NULL"
).fetchone()[0]
print("TOTAL:", total)
c.close()
