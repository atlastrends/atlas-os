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
import re
import shutil
import subprocess
import sys
import tempfile
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


def _max_upload_bytes() -> int:
    """Limite de tamanho por arquivo do bucket (MB). Padrao 49 MB (plano free)."""
    try:
        mb = float(str(os.getenv("SUPABASE_MAX_UPLOAD_MB", "49")).strip())
    except (TypeError, ValueError):
        mb = 49.0
    return int(mb * 1024 * 1024)


def _ffmpeg_exe() -> str | None:
    """Localiza o ffmpeg (PATH, venv ou o embutido no imageio-ffmpeg)."""
    cand = shutil.which("ffmpeg")
    if cand:
        return cand
    exe = Path(sys.executable).parent / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if exe.is_file():
        return str(exe)
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _probe_duration(ffmpeg: str, file: Path) -> float:
    """Duracao em segundos, lendo o stderr do ffmpeg (sem depender de ffprobe)."""
    try:
        proc = subprocess.run(
            [ffmpeg, "-i", str(file)], capture_output=True, text=True, timeout=60
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def _transcode(ffmpeg: str, src: Path, dst: Path, video_kbps: int, scale: bool) -> bool:
    """Reencoda 'src' para 'dst' num bitrate alvo. scale=True reduz para 720p."""
    cmd = [ffmpeg, "-y", "-i", str(src)]
    if scale:
        cmd += ["-vf", "scale=-2:1280"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{video_kbps}k",
        "-maxrate", f"{int(video_kbps * 1.2)}k",
        "-bufsize", f"{video_kbps * 2}k",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
    except Exception as exc:  # pragma: no cover - depende do ffmpeg
        log.warning("Falha ao comprimir video para upload: %s", exc)
        return False


def _compress_for_upload(file: Path, max_bytes: int) -> tuple[Path, bool]:
    """Se o video passar do limite do bucket, gera uma copia menor num arquivo
    temporario (o original no disco NAO e alterado).

    Retorna (arquivo_para_subir, e_temporario).
    """
    try:
        if file.stat().st_size <= max_bytes:
            return file, False
    except OSError:
        return file, False

    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        log.warning("Video maior que o limite e ffmpeg indisponivel; upload pode falhar.")
        return file, False

    duration = _probe_duration(ffmpeg, file) or 60.0
    # bitrate total que cabe no limite (com folga de 10%), menos o audio (128k).
    target_bytes = int(max_bytes * 0.90)
    total_kbps = max(600, int(target_bytes * 8 / duration / 1000))
    video_kbps = max(500, total_kbps - 128)

    tmp = Path(tempfile.gettempdir()) / f"atlas_up_{_object_name(file)}"
    # 1a tentativa: mantem a resolucao original.
    if _transcode(ffmpeg, file, tmp, video_kbps, scale=False) and tmp.stat().st_size <= max_bytes:
        log.info(
            "Video comprimido para upload: %.1f MB -> %.1f MB",
            file.stat().st_size / 1048576,
            tmp.stat().st_size / 1048576,
        )
        return tmp, True
    # 2a tentativa: reduz para 720p e baixa mais o bitrate.
    if _transcode(ffmpeg, file, tmp, int(video_kbps * 0.8), scale=True) and tmp.stat().st_size <= max_bytes:
        log.info(
            "Video comprimido (720p) para upload: %.1f MB -> %.1f MB",
            file.stat().st_size / 1048576,
            tmp.stat().st_size / 1048576,
        )
        return tmp, True

    try:
        if tmp.is_file():
            tmp.unlink()
    except OSError:
        pass
    log.warning("Nao foi possivel comprimir o video abaixo do limite do bucket.")
    return file, False


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

    # O nome do objeto (e a URL publica) segue SEMPRE o arquivo original, para o
    # cache e o link ficarem estaveis mesmo quando subimos uma copia comprimida.
    name = _object_name(file)
    endpoint = f"{url}/storage/v1/object/{bucket}/{name}"

    # Reels podem passar do limite do bucket (ex.: 50 MB no plano free) -> o
    # upload dava 413 e a publicacao caia para localhost. Aqui subimos uma copia
    # menor quando necessario (o arquivo original no disco fica intacto).
    upload_file, is_temp = _compress_for_upload(file, _max_upload_bytes())
    ctype = mimetypes.guess_type(upload_file.name)[0] or "video/mp4"
    try:
        with upload_file.open("rb") as fh:
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
    finally:
        if is_temp:
            try:
                upload_file.unlink()
            except OSError:
                pass

    public = f"{url}/storage/v1/object/public/{bucket}/{name}"
    _uploaded[abspath] = public
    log.info("Video no armazenamento publico: %s", public)
    return public
