# ATLAS OS - Conector Instagram (Instagram Graph API - Reels)
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time

import requests

from app.publishing.base import (
    BasePublisher,
    MetaGraphTransientError,
    PublishRequest,
    PublishResult,
    get_page_access_token,
    local_media_file,
    public_media_url,
    resolve_meta_targets,
)

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Intervalos (segundos) entre as checagens de processamento do Reels. Usa
# backoff e poucas checagens (12) em vez de 30 chamadas fixas de 5s, para
# gastar bem menos o limite de requisicoes do app da Meta. Soma ~3 minutos.
_IG_STATUS_POLL_DELAYS = (5, 5, 8, 10, 12, 15, 18, 20, 22, 25, 30, 30)

# Acima deste bitrate de video (kb/s) o Instagram costuma REJEITAR o Reel no
# processamento ("ProcessingFailedError / Request processing failed"). Os reels
# de trend saem em ~9000 kb/s / perfil Baseline (preset ultrafast), que o
# Facebook aceita mas o IG nao. Normalizamos so para o IG.
_IG_MAX_VIDEO_KBPS = int(os.getenv("ATLAS_IG_MAX_VIDEO_KBPS", "6500"))
# Alvo de bitrate do transcode para IG. Mantemos o arquivo pequeno (~20 MB) -
# a MESMA faixa dos videos de afiliado que sobem sem problema. O envio de bytes
# do IG e confiavel para arquivos pequenos e INSTAVEL para grandes (o reel de
# trend a 9 Mbps da 70-96 MB). ~2800 kbps num reel de 60s da ~21 MB.
_IG_TARGET_VIDEO_BITRATE = os.getenv("ATLAS_IG_TARGET_VIDEO_BITRATE", "2800k")
_IG_TARGET_MAXRATE = os.getenv("ATLAS_IG_TARGET_MAXRATE", "3400k")
# O IG Reels (via API) REJEITA video com 60s ou mais ("ProcessingFailedError").
# Videos abaixo de 60s publicam; a partir de ~60s a Meta recusa no
# processamento. Capamos a duracao SO para o IG (o Reels do trend sai com
# 60-90s e publica normal no YouTube/Facebook).
_IG_MAX_DURATION = float(os.getenv("ATLAS_IG_MAX_DURATION_SECONDS", "0"))
# O upload resumavel do IG as vezes devolve "ProcessingFailedError" de forma
# INTERMITENTE (o processamento da Meta falha e volta), com mais frequencia em
# arquivos grandes / perfil Baseline. Retentamos o container+upload algumas
# vezes com backoff antes de desistir.
_IG_UPLOAD_ATTEMPTS = int(os.getenv("ATLAS_IG_UPLOAD_ATTEMPTS", "4"))
_IG_RETRY_BACKOFF = (5, 12, 25, 40)


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")


def _probe_video(path: str) -> dict:
    """Le perfil H.264 e bitrate do video via `ffmpeg -i` (sem depender de
    ffprobe, que nao vem no imageio-ffmpeg). Retorna {profile, kbps}."""
    info = {"profile": "", "kbps": 0, "duration": 0.0}
    try:
        proc = subprocess.run(
            [_ffmpeg_exe(), "-hide_banner", "-i", path],
            capture_output=True, text=True, timeout=60,
        )
        text = (proc.stderr or "") + (proc.stdout or "")
        m = re.search(r"Video:\s*h264\s*\(([^)]+)\)", text)
        if m:
            info["profile"] = m.group(1).strip()
        # Bitrate do stream de video ("..., 9013 kb/s, 30 fps"); se nao houver,
        # cai para o bitrate geral do arquivo ("bitrate: 9123 kb/s").
        mv = re.search(r"Video:.*?,\s*(\d+)\s*kb/s", text)
        mo = re.search(r"bitrate:\s*(\d+)\s*kb/s", text)
        if mv:
            info["kbps"] = int(mv.group(1))
        elif mo:
            info["kbps"] = int(mo.group(1))
        md = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", text)
        if md:
            info["duration"] = (
                int(md.group(1)) * 3600 + int(md.group(2)) * 60 + float(md.group(3))
            )
    except Exception:  # noqa: BLE001
        pass
    return info


def _needs_ig_transcode(path: str) -> bool:
    """Decide se o video precisa ser re-encodado para o padrao do IG Reels.
    True quando o perfil H.264 e Baseline OU o bitrate esta acima do limite.
    (NAO mexe na duracao - nao cortamos video.)"""
    probe = _probe_video(path)
    profile = probe.get("profile", "").lower()
    kbps = probe.get("kbps", 0)
    if "baseline" in profile:
        return True
    if kbps and kbps > _IG_MAX_VIDEO_KBPS:
        return True
    # Sem leitura confiavel: usa o tamanho como salvaguarda (arquivos grandes
    # sao os reels de ~9 Mbps que o IG rejeita; afiliados ~10 MB passam).
    if not profile and not kbps:
        try:
            if os.path.getsize(path) > 25 * 1024 * 1024:
                return True
        except OSError:
            return False
    return False


def _make_ig_compliant(path: str) -> str | None:
    """Gera uma copia temporaria no padrao ACEITO pelo IG Reels (H.264 High,
    yuv420p, bitrate limitado, AAC, +faststart). NAO corta a duracao. Retorna o
    caminho temporario ou None se falhar (ai o chamador tenta o original)."""
    try:
        fd, out = tempfile.mkstemp(prefix="ig_reel_", suffix=".mp4")
        os.close(fd)
        cmd = [
            _ffmpeg_exe(), "-y", "-i", path,
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.1",
            "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-b:v", _IG_TARGET_VIDEO_BITRATE,
            "-maxrate", _IG_TARGET_MAXRATE, "-bufsize", "10000k",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 50 * 1024:
            return out
        try:
            os.remove(out)
        except OSError:
            pass
    except Exception:  # noqa: BLE001
        pass
    return None


class InstagramPublisher(BasePublisher):
    platform = "instagram"
    required_env = (
        "META_ACCESS_TOKEN",
    )

    def _do_publish(self, request: PublishRequest) -> PublishResult:
        page_id, ig_id, role, market = resolve_meta_targets(
            request.kind,
            request.country_code,
            request.language,
        )

        if not ig_id:
            return PublishResult(
                status="credentials_missing",
                error=(
                    "Conta do Instagram nao configurada para "
                    f"{role}/{market}. Defina IG_{role}_{market} no .env."
                ),
                detail={"platform": self.platform, "role": role, "market": market},
            )

        # O Instagram Graph API tambem exige o token da Pagina do Facebook
        # conectada aquela conta do Instagram (nao o token de usuario puro).
        try:
            token = get_page_access_token(page_id)
        except MetaGraphTransientError as exc:
            return PublishResult(
                status="failed",
                error=f"Bloqueio temporario do Graph API (Meta): {exc}",
                detail={"platform": self.platform, "role": role, "market": market},
            )

        # Preferimos enviar os BYTES locais direto (upload resumavel), sem URL
        # publica: isso elimina de vez o "403 Restricted by robots.txt". So
        # caimos para video_url se o arquivo local nao existir mais.
        local_file = local_media_file(request.video_path)
        video_url = public_media_url(request.video_path)
        if not local_file and (not video_url or video_url.startswith("http://localhost")):
            return PublishResult(
                status="failed",
                error=(
                    "O arquivo local do video nao existe e nao ha URL PUBLICA "
                    "para o Instagram baixar. Mantenha o MP4 no disco (nao purgar "
                    "antes de publicar) ou defina ATLAS_PUBLIC_BASE_URL HTTPS."
                ),
                detail={"platform": self.platform, "video_url": video_url},
            )

        caption = (request.caption or request.description or "").strip()

        # Normaliza o video para o padrao aceito pelo IG (High, bitrate
        # controlado) UMA vez - os reels de trend saem ~9 Mbps Baseline, que o
        # processamento do IG rejeita com mais frequencia. NAO corta a duracao.
        upload_source = local_file
        temp_transcode = None
        if local_file and _needs_ig_transcode(local_file):
            temp_transcode = _make_ig_compliant(local_file)
            if temp_transcode:
                upload_source = temp_transcode

        try:
            # Cria o container e envia os bytes, RETENTANDO em caso de
            # ProcessingFailedError (falha intermitente do processamento da Meta).
            container_id = None
            last_error = ""
            for attempt in range(_IG_UPLOAD_ATTEMPTS):
                # 1) Container de midia (REELS). Local -> resumavel; senao URL.
                if local_file:
                    create = requests.post(
                        f"{GRAPH_BASE}/{ig_id}/media",
                        data={
                            "media_type": "REELS",
                            "upload_type": "resumable",
                            "caption": caption,
                            "access_token": token,
                        },
                        timeout=60,
                    )
                else:
                    create = requests.post(
                        f"{GRAPH_BASE}/{ig_id}/media",
                        data={
                            "media_type": "REELS",
                            "video_url": video_url,
                            "caption": caption,
                            "access_token": token,
                        },
                        timeout=60,
                    )
                create_data = create.json()
                if create.status_code >= 400 or "id" not in create_data:
                    last_error = f"criar container: {create_data}"
                    time.sleep(_IG_RETRY_BACKOFF[min(attempt, len(_IG_RETRY_BACKOFF) - 1)])
                    continue
                container_id = create_data["id"]

                # 2) Modo URL: sem upload de bytes; segue para o processamento.
                if not local_file:
                    break

                # 3) Envia os BYTES do arquivo (sem URL publica / robots.txt).
                file_size = os.path.getsize(upload_source)
                upload_uri = create_data.get("uri") or (
                    f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{container_id}"
                )
                with open(upload_source, "rb") as fh:
                    up = requests.post(
                        upload_uri,
                        headers={
                            "Authorization": f"OAuth {token}",
                            "offset": "0",
                            "file_size": str(file_size),
                        },
                        data=fh,
                        timeout=600,
                    )
                if up.status_code < 400:
                    break  # upload OK
                last_error = up.text
                container_id = None  # container queimado: recria na proxima
                time.sleep(_IG_RETRY_BACKOFF[min(attempt, len(_IG_RETRY_BACKOFF) - 1)])

            if not container_id:
                return PublishResult(
                    status="failed",
                    error=(
                        f"Falha no upload do Reels (IG) apos {_IG_UPLOAD_ATTEMPTS} "
                        f"tentativas: {last_error}"
                    ),
                    detail={
                        "platform": self.platform,
                        "upload_mode": "local_bytes" if local_file else "video_url",
                    },
                )

            # 2) Aguarda o processamento do video ficar pronto. Faz poucas
            #    checagens espacadas (backoff) para nao gastar o limite de
            #    requisicoes do app da Meta. Se o Graph responder com erro
            #    TEMPORARIO (ex.: "(#4) Application request limit reached"),
            #    para de checar na hora e devolve como bloqueio temporario
            #    (o servico reenvia depois), em vez de insistir dezenas de
            #    vezes e piorar o rate-limit.
            for delay in _IG_STATUS_POLL_DELAYS:
                status = requests.get(
                    f"{GRAPH_BASE}/{container_id}",
                    params={"fields": "status_code", "access_token": token},
                    timeout=30,
                ).json()
                if isinstance(status, dict) and "error" in status:
                    return PublishResult(
                        status="failed",
                        error=(
                            "Bloqueio temporario do Graph API (Meta) ao checar "
                            f"o processamento do Reels: {status['error']}"
                        ),
                        detail={"platform": self.platform},
                    )
                code = status.get("status_code")
                if code == "FINISHED":
                    break
                if code == "ERROR":
                    return PublishResult(
                        status="failed",
                        error=f"Instagram falhou ao processar o video: {status}",
                        detail={"platform": self.platform},
                    )
                time.sleep(delay)
            else:
                return PublishResult(
                    status="failed",
                    error="Tempo esgotado aguardando o Instagram processar o video.",
                    detail={"platform": self.platform},
                )

            # 3) Publica o container.
            publish = requests.post(
                f"{GRAPH_BASE}/{ig_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
                timeout=60,
            )
            publish_data = publish.json()
            media_id = publish_data.get("id")
            if publish.status_code >= 400 or not media_id:
                return PublishResult(
                    status="failed",
                    error=f"Falha ao publicar o Reels: {publish_data}",
                    detail={"platform": self.platform},
                )

            # 4) Busca o link real (permalink) para conferir o Reels.
            #    O ID numerico NAO forma uma URL valida; o permalink usa
            #    um codigo curto que so a API do Instagram devolve.
            permalink = f"https://www.instagram.com/reel/{media_id}"
            try:
                info = requests.get(
                    f"{GRAPH_BASE}/{media_id}",
                    params={"fields": "permalink", "access_token": token},
                    timeout=30,
                ).json()
                real = (info or {}).get("permalink")
                if real:
                    permalink = real
            except Exception:  # noqa: BLE001
                pass

            return PublishResult(
                status="published",
                external_id=media_id,
                external_url=permalink,
                detail={"platform": self.platform},
            )

        except Exception as exc:  # noqa: BLE001
            return PublishResult(
                status="failed",
                error=f"Erro na publicacao do Instagram: {exc}",
                detail={"platform": self.platform},
            )
        finally:
            if temp_transcode:
                try:
                    os.remove(temp_transcode)
                except OSError:
                    pass
