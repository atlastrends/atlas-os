# -*- coding: utf-8 -*-
"""Mostra qual conta do TikTok esta conectada (BR/US) - para conferir se os
rascunhos foram limpos na conta certa. READ-ONLY, nao publica nada."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

import requests

from app.services import tiktok_oauth_service

USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"


def conta(market: str) -> None:
    token = tiktok_oauth_service.get_access_token(market)
    if not token:
        print(f"[{market}] sem token (nao conectado)")
        return
    try:
        r = requests.get(
            USER_INFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "open_id,display_name,username"},
            timeout=30,
        )
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[{market}] erro ao consultar: {exc}")
        return
    user = (data.get("data") or {}).get("user") or {}
    err = (data.get("error") or {})
    code = (err.get("code") or "").lower()
    nome = user.get("display_name") or "(sem nome)"
    username = user.get("username") or "(username indisponivel no scope basic)"
    print(f"[{market}] conta conectada: {nome}  |  @{username}")
    if code and code != "ok":
        print(f"[{market}] aviso da API: {code} - {err.get('message')}")


def main() -> int:
    for m in ("BR", "US"):
        conta(m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
