"""Diagnostico READ-ONLY dos erros de Instagram/Facebook (Meta Graph API).

Roda direto no SQLite local (atlas_local.db) sem alterar nada. Mostra:
  1) contagem por plataforma/status
  2) top mensagens de erro (nao concluidas)
  3) publicacoes mais recentes de IG/FB (para ver o que acontece AGORA)

Uso: .\.venv-dash\Scripts\python.exe tools\diag_meta_errors.py
"""
from __future__ import annotations

import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "atlas_local.db")


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    print("== CONTAGEM por plataforma/status (IG+FB) ==")
    for row in cur.execute(
        """
        SELECT platform, status, COUNT(*) n, MAX(updated_at) last
        FROM publications
        WHERE platform IN ('instagram','facebook')
        GROUP BY platform, status
        ORDER BY platform, n DESC
        """
    ):
        print(f"  {row[0]:10} {row[1]:20} n={row[2]:4}  last={row[3]}")

    print("\n== TOP mensagens de erro (IG+FB, nao concluidas) ==")
    for row in cur.execute(
        """
        SELECT platform,
               SUBSTR(REPLACE(REPLACE(error,char(10),' '),char(13),' '),1,150) err,
               COUNT(*) n, MAX(updated_at) last
        FROM publications
        WHERE platform IN ('instagram','facebook')
          AND status NOT IN ('published','skipped')
          AND error IS NOT NULL
        GROUP BY platform, err
        ORDER BY n DESC
        LIMIT 25
        """
    ):
        print(f"  [{row[0]}] n={row[2]:4} last={row[3]}")
        print(f"      {row[1]}")

    print("\n== 15 mais RECENTES (IG+FB, qualquer status) ==")
    for row in cur.execute(
        """
        SELECT updated_at, platform, status, video_asset_id,
               SUBSTR(REPLACE(REPLACE(COALESCE(error,''),char(10),' '),char(13),' '),1,120) err
        FROM publications
        WHERE platform IN ('instagram','facebook')
        ORDER BY updated_at DESC
        LIMIT 15
        """
    ):
        print(f"  {row[0]}  {row[1]:10} {row[2]:18} asset={row[3]}")
        if row[4]:
            print(f"      {row[4]}")

    con.close()


if __name__ == "__main__":
    main()
