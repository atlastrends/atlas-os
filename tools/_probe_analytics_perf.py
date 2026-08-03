"""Read-only: analise de desempenho da tela Analytics/Estatistica.
Mede: contagem de linhas, latencia HTTP de cada endpoint e o EXPLAIN QUERY
PLAN das consultas suspeitas. Nao altera nada. Seguro apagar."""
import sqlite3
import statistics
import time
import urllib.request

DB = r"C:\atlas-os\atlas_local.db"
BASE = "http://127.0.0.1:8000"


def counts() -> None:
    con = sqlite3.connect(DB)
    for t in ("video_assets", "video_metrics", "platform_stats",
              "publications", "short_links", "link_clicks"):
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            n = f"(erro: {e})"
        print(f"  {t:16} {n}")
    con.close()


def time_get(path: str, runs: int = 3) -> list[float]:
    out: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(BASE + path, timeout=90) as r:
                r.read()
            out.append((time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            print("   ERRO", path, e)
            out.append(-1.0)
    return out


def explain(title: str, sql: str, params: tuple = ()) -> None:
    print(f"\n=== EXPLAIN: {title} ===")
    con = sqlite3.connect(DB)
    try:
        for row in con.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall():
            print("   ", row[-1])
    except Exception as e:  # noqa: BLE001
        print("   (erro:", e, ")")
    con.close()


def main() -> None:
    print("=== Contagem de linhas ===")
    counts()

    print("\n=== Latencia HTTP (ms, 3 execucoes) ===")
    for p in ("/api/analytics/overview", "/api/analytics/platforms",
              "/api/analytics/accounts", "/api/analytics/top-videos",
              "/api/status"):
        ts = time_get(p)
        good = [t for t in ts if t >= 0]
        med = statistics.median(good) if good else -1
        shown = ", ".join(f"{t:.0f}" for t in ts)
        print(f"  {p:32} [{shown}]  mediana={med:.0f} ms")

    explain(
        "_latest_account_stats (1x por conta, ~10 contas por load)",
        "SELECT * FROM platform_stats WHERE account=? "
        "ORDER BY captured_at DESC LIMIT 1",
        ("tiktok.all.BR",),
    )
    explain(
        "greatest-per-group video_metrics (usado em overview/platforms/top)",
        "SELECT video_asset_id, platform, MAX(captured_at) "
        "FROM video_metrics GROUP BY video_asset_id, platform",
    )


if __name__ == "__main__":
    main()
