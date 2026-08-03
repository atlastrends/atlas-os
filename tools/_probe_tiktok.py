"""Read-only: show connected TikTok accounts and their market routing labels,
plus recent tiktok publications, to diagnose cross-account posting."""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print("=== tiktok_accounts (routing) ===")
    rows = list(con.execute(
        "SELECT id, open_id, display_name, market, "
        "(access_token IS NOT NULL AND access_token<>'') AS has_access, "
        "(refresh_token IS NOT NULL AND refresh_token<>'') AS has_refresh, "
        "updated_at FROM tiktok_accounts ORDER BY market, id"
    ))
    if not rows:
        print("  (NENHUMA conta TikTok conectada no banco)")
    for r in rows:
        print(
            f"  id#{r['id']}  market={r['market']!r:8}  name={str(r['display_name'])[:24]!r:26}"
            f"  open_id=...{str(r['open_id'])[-8:]}  access={bool(r['has_access'])} refresh={bool(r['has_refresh'])}"
            f"  upd={str(r['updated_at'])[:19]}"
        )

    print("\n=== ultimas 10 publicacoes TikTok (asset market vs conta) ===")
    q = """
        SELECT p.id AS pid, p.status, p.created_at, p.external_id,
               va.kind, va.country_code, va.language, va.title
        FROM publications p JOIN video_assets va ON va.id=p.video_asset_id
        WHERE p.platform='tiktok'
        ORDER BY p.created_at DESC LIMIT 10
    """
    for r in con.execute(q):
        print(
            f"  pub#{r['pid']:<4} {r['status']:<12} {str(r['created_at'])[:19]}"
            f"  cc={str(r['country_code'])!r:6} lang={str(r['language'])!r:8} {r['kind']:<9}"
            f"  ext_id={str(r['external_id'])[:16]!r}  T={str(r['title'])[:34]!r}"
        )
    con.close()


if __name__ == "__main__":
    main()
