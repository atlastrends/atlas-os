"""Envio de videos para um armazenamento publico na nuvem (Supabase Storage).

Para que? Instagram e Facebook precisam BAIXAR o video de uma URL publica
(https). No PC corporativo o tunel (cloudflared) e bloqueado pelo firewall,
mas o HTTPS normal funciona. Entao, quando o Atlas vai publicar, ele SOBE o
video para o Supabase (por HTTPS comum) e passa a URL publica desse arquivo
para o Instagram/Facebook.

Como ligar (no arquivo .env):
    SUPABASE_URL=https://xxxxxxxx.supabase.co
    SUPABASE_SERVICE_KEY=eyJhbGciOi...      (chave "service_role" do projeto)
    SUPABASE_BUCKET=atlas-videos            (um bucket PUBLICO criado no painel)

Se essas variaveis nao estiverem preenchidas, este modulo fica desligado e o
sistema volta a usar o tunel/localhost automaticamente.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from pathlib import Path

import requests

log = logging.getLogger("atlas.media_storage")

# Cache por processo: caminho local -> URL publica (evita subir 2x o mesmo
# video quando IG e FB publicam em seguida).
_uploaded: dict[str, str] = {}


def _cfg() -> tuple[str, str, str]:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_KEY")
        or ""
    ).strip()
    bucket = (os.getenv("SUPABASE_BUCKET") or "atlas-videos").strip()
    return url, key, bucket


def is_enabled() -> bool:
    """True quando o armazenamento na nuvem esta configurado."""
    url, key, bucket = _cfg()
    return bool(url and key and bucket)


def _resolve_file(local_path: str) -> Path | None:
    p = Path(local_path)
    if p.is_file():
        return p
    # tenta relativo a raiz do projeto
    try:
        from app.publishing.base import project_root

        alt = Path(project_root()) / local_path
        if alt.is_file():
            return alt
    except Exception:
        pass
    return None


def _object_name(file: Path) -> str:
    h = hashlib.sha1(str(file.resolve()).encode()).hexdigest()[:10]
    safe = file.name.replace(" ", "_")
    return f"{h}_{safe}"


def get_or_upload_public_url(local_path: str) -> str:
    """Sobe o video (se ainda nao subiu) e devolve a URL publica; '' se falhar."""
    if not local_path:
        return ""
    abspath = str(Path(local_path).resolve())
    if abspath in _uploaded:
        return _uploaded[abspath]

    url, key, bucket = _cfg()
    if not (url and key and bucket):
        return ""

    file = _resolve_file(local_path)
    if file is None:
        log.warning("Arquivo de video nao encontrado para upload: %s", local_path)
        return ""

    name = _object_name(file)
    ctype = mimetypes.guess_type(file.name)[0] or "video/mp4"
    endpoint = f"{url}/storage/v1/object/{bucket}/{name}"
    try:
        with file.open("rb") as fh:
            resp = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {key}",
                    "apikey": key,
                    "Content-Type": ctype,
                    "x-upsert": "true",  # substitui se ja existir
                },
                data=fh,
                timeout=600,
            )
        if resp.status_code >= 400:
            log.warning(
                "Upload Supabase falhou (%s): %s", resp.status_code, resp.text[:300]
            )
            return ""
    except Exception as exc:  # pragma: no cover - rede
        log.warning("Upload Supabase erro: %s", exc)
        return ""

    public = f"{url}/storage/v1/object/public/{bucket}/{name}"
    _uploaded[abspath] = public
    log.info("Video no armazenamento publico: %s", public)
    return public
