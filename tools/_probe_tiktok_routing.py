"""Read-only: prova a separacao estrita do roteamento TikTok por mercado.
Mostra, para BR e US, qual conta (se houver) seria escolhida. NAO renova
tokens nem faz chamadas de rede. Seguro apagar."""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print("=== Contas TikTok conectadas (banco) ===")
    rows = list(con.execute(
        "SELECT id, market, display_name, open_id, "
        "CASE WHEN access_token IS NOT NULL AND length(access_token)>0 THEN 1 ELSE 0 END AS has_token "
        "FROM tiktok_accounts ORDER BY market, id"
    ))
    if not rows:
        print("  (nenhuma)")
    for r in rows:
        print(f"  id#{r['id']}  market={r['market']!r:6}  nome={r['display_name']!r}  token={'sim' if r['has_token'] else 'nao'}")

    print("\n=== Roteamento estrito (quem publica cada mercado) ===")
    for market in ("BR", "US"):
        acc = con.execute(
            "SELECT id, display_name FROM tiktok_accounts WHERE market=? "
            "ORDER BY updated_at DESC LIMIT 1",
            (market,),
        ).fetchone()
        if acc:
            print(f"  {market}: publica em -> {acc['display_name']!r} (id#{acc['id']})")
        else:
            print(f"  {market}: SEM conta -> NAO publica (pede para conectar). Sem vazamento.")
    con.close()


if __name__ == "__main__":
    main()
