"""Read-only: diagnostico do token TikTok (por que a conexao cai).
Mostra validade do access_token, presenca do refresh_token, scopes e datas.
NAO faz chamadas de rede nem renova nada. Seguro apagar."""
import os
import sqlite3
import time
from datetime import datetime, timezone

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def human(seconds: int) -> str:
    seconds = int(seconds)
    sign = "" if seconds >= 0 else "-"
    seconds = abs(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}min")
    return sign + (" ".join(parts) or "0min")


def main() -> None:
    now = int(time.time())
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = list(con.execute(
        "SELECT id, market, display_name, open_id, access_token, refresh_token, "
        "token_expires_at, scopes, created_at, updated_at FROM tiktok_accounts "
        "ORDER BY market, id"
    ))
    if not rows:
        print("Nenhuma conta TikTok conectada.")
        return
    for r in rows:
        exp = int(r["token_expires_at"] or 0)
        has_a = bool((r["access_token"] or "").strip())
        has_r = bool((r["refresh_token"] or "").strip())
        print(f"=== id#{r['id']}  market={r['market']!r}  nome={r['display_name']!r} ===")
        print(f"  access_token presente : {'sim' if has_a else 'NAO'}")
        print(f"  refresh_token presente: {'sim' if has_r else 'NAO'}  <-- chave da renovacao automatica")
        if exp:
            delta = exp - now
            when = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
            if delta >= 0:
                print(f"  access_token expira em: {when}  (daqui a {human(delta)})")
            else:
                print(f"  access_token EXPIROU em: {when}  (ha {human(-delta)})  <- normal: dura ~24h, e renovado sob demanda")
        else:
            print("  access_token expira em: (sem data)")
        print(f"  scopes                : {r['scopes']!r}")
        print(f"  conectado em          : {r['created_at']}")
        print(f"  atualizado em         : {r['updated_at']}  <- ultima renovacao/uso")
        print()
    con.close()


if __name__ == "__main__":
    main()
