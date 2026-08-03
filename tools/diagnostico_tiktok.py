# -*- coding: utf-8 -*-
"""Diagnostico AO VIVO do TikTok (READ-ONLY + sondagem sem criar rascunho).

Responde: "limpei os rascunhos, por que ainda nao esta indo?".

Parte A: estado no banco (quantas publicacoes do TikTok por status + erros).
Parte B: conexao/token (BR/US conectado? consegue gerar access_token? modo
         Direct Post ou rascunho? scopes) - SEM imprimir segredos.
Parte C: SONDAGEM REAL - chama o endpoint de init do TikTok com o tamanho de um
         video real, mas NAO envia os bytes (nao cria rascunho). Mostra a
         resposta crua do TikTok agora (spam_risk ainda? ou liberou?).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.env_loader import load_env

load_env()

import requests

from app.core.database import SessionLocal
from app.models.dashboard import (
    Publication,
    PublicationStatusEnum,
    VideoAsset,
)
from app.publishing.base import resolve_video_path
from app.services import tiktok_oauth_service

API_BASE = "https://open.tiktokapis.com/v2"
_MAX_SINGLE_CHUNK = 64 * 1024 * 1024
_DEFAULT_CHUNK = 20 * 1024 * 1024


def _plan_chunks(video_size: int):
    if video_size <= _MAX_SINGLE_CHUNK:
        return video_size, 1
    chunk_size = _DEFAULT_CHUNK
    total = video_size // chunk_size
    return chunk_size, max(total, 1)


def parte_a(db) -> None:
    print("=" * 60)
    print("PARTE A - estado das publicacoes do TikTok no banco")
    print("=" * 60)
    pubs = (
        db.query(Publication)
        .filter(Publication.platform == "tiktok")
        .all()
    )
    by_status: dict[str, int] = {}
    for p in pubs:
        s = getattr(p.status, "value", p.status)
        by_status[s] = by_status.get(s, 0) + 1
    print(f"Total de publicacoes TikTok: {len(pubs)}")
    for s, n in sorted(by_status.items()):
        print(f"  {s:20s} {n}")

    # Erros mais recentes (nao concluidos)
    pendentes = [
        p
        for p in pubs
        if getattr(p.status, "value", p.status)
        not in ("published", "skipped")
        and (p.error or "").strip()
    ]
    print(f"\nPublicacoes TikTok NAO concluidas com erro: {len(pendentes)}")
    vistos: set[str] = set()
    mostrados = 0
    for p in sorted(pendentes, key=lambda x: x.id, reverse=True):
        err = (p.error or "").strip()
        chave = err[:60]
        if chave in vistos:
            continue
        vistos.add(chave)
        print(f"  asset #{p.video_asset_id}: {err[:160]}")
        mostrados += 1
        if mostrados >= 6:
            break


def parte_b() -> None:
    print("\n" + "=" * 60)
    print("PARTE B - conexao / token / modo de publicacao")
    print("=" * 60)
    st = tiktok_oauth_service.status()
    print(f"has_client (client key+secret): {st['has_client']}")
    print(f"redirect_uri https: {st['is_public_https']}")
    for m, info in (st.get("markets") or {}).items():
        print(
            f"  mercado {m}: connected={info['connected']} "
            f"has_refresh={info['has_refresh']} open_id={'sim' if info['open_id'] else 'nao'}"
        )
    # Modo de publicacao
    scopes = (os.getenv("TIKTOK_SCOPES") or "user.info.basic,video.upload").lower()
    direct_enabled = (os.getenv("TIKTOK_DIRECT_POST") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    direct_post = direct_enabled and "video.publish" in scopes
    print(f"\nTIKTOK_DIRECT_POST habilitado: {direct_enabled}")
    print(f"scope tem video.publish: {'video.publish' in scopes}")
    print(f"=> MODO EFETIVO: {'DIRECT POST (posta no perfil)' if direct_post else 'RASCUNHO/INBOX (vai p/ Caixa de entrada do app)'}")
    privacy = os.getenv("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")
    print(f"privacy_level: {privacy}")


def parte_c(db) -> None:
    print("\n" + "=" * 60)
    print("PARTE C - SONDAGEM REAL no TikTok (init, sem criar rascunho)")
    print("=" * 60)
    # Acha um asset com arquivo de video valido (novos/pendentes ainda tem arquivo).
    candidatos = (
        db.query(VideoAsset)
        .order_by(VideoAsset.id.desc())
        .limit(400)
        .all()
    )
    escolhido = None
    caminho = None
    tamanho = 0
    for a in candidatos:
        vp = (a.video_path or "").strip()
        if not vp:
            continue
        full = resolve_video_path(vp)
        if full and os.path.isfile(full):
            try:
                sz = os.path.getsize(full)
            except OSError:
                continue
            if sz > 0:
                escolhido = a
                caminho = full
                tamanho = sz
                break
    if not escolhido:
        print("Nao achei nenhum arquivo de video valido para sondar.")
        return
    print(f"Usando asset #{escolhido.id} arquivo={os.path.basename(caminho)} ({tamanho/1024/1024:.1f} MB)")

    market = "BR"
    token = tiktok_oauth_service.get_access_token(market)
    print(f"Token BR obtido: {'sim' if token else 'NAO'} (len={len(token) if token else 0})")
    if not token:
        print("Sem token -> conta nao conectada. Precisa reconectar o TikTok no painel.")
        return

    chunk_size, total = _plan_chunks(tamanho)
    init_url = f"{API_BASE}/post/publish/inbox/video/init/"
    init_body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": tamanho,
            "chunk_size": chunk_size,
            "total_chunk_count": total,
        }
    }
    try:
        r = requests.post(
            init_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=init_body,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERRO de rede na sondagem: {exc}")
        return

    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        print(f"Resposta nao-JSON: {r.text[:300]}")
        return
    err = (data.get("error") or {})
    code = (err.get("code") or "").lower()
    msg = err.get("message") or ""
    print(f"error.code = {code!r}")
    print(f"error.message = {msg!r}")
    if code and code != "ok":
        if "spam_risk" in code or "pending_share" in code:
            print("\n>>> AINDA BLOQUEADO por rascunhos pendentes (spam_risk).")
            print(">>> O TikTok ainda ve rascunhos/janela nao liberada.")
        else:
            print(f"\n>>> Erro diferente de spam_risk: {code}")
    else:
        pub_id = (data.get("data") or {}).get("publish_id")
        print("\n>>> LIBEROU! init OK, publish_id=" + str(pub_id))
        print(">>> spam_risk NAO aparece mais. Pode reenviar para o TikTok agora.")
        print(">>> (Nao enviei os bytes; nenhum rascunho foi criado.)")


def main() -> int:
    db = SessionLocal()
    try:
        parte_a(db)
        parte_b()
        parte_c(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
