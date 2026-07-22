# ============================================================
# ATLAS OS - services/live_avatar_service.py
#
# "Rosto que fala" da live. Transforma a VOZ (mp3) do apresentador
# em um VIDEO curto do apresentador falando.
#
# Motores (engine) plugaveis via variavel de ambiente ATLAS_AVATAR_ENGINE:
#   - "ffmpeg"   -> imagem parada + audio -> mp4 (SEM placa de video).
#                   Roda em qualquer PC. Serve para testar o pipeline.
#   - "wav2lip"  -> lip-sync REAL (boca mexendo). Precisa de placa NVIDIA
#                   (roda no Dell G15). Configurado por variaveis de ambiente
#                   (ver _wav2lip). Se nao estiver instalado, cai no ffmpeg.
#
# A ideia: montamos e testamos tudo com o motor "ffmpeg" aqui; no G15
# basta instalar o Wav2Lip e trocar ATLAS_AVATAR_ENGINE=wav2lip.
# ============================================================

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

_ATLAS_ROOT = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
_CLIP_DIR = _ATLAS_ROOT / "storage" / "live" / "clips"
_PRESENTER_DIR = _ATLAS_ROOT / "storage" / "live" / "presenter"

# Motor padrao: ffmpeg (sem placa). No G15: defina ATLAS_AVATAR_ENGINE=wav2lip.
_ENGINE = (os.getenv("ATLAS_AVATAR_ENGINE", "ffmpeg") or "ffmpeg").strip().lower()

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# Tamanho do palco vertical (9:16) usado no motor ffmpeg.
_STAGE_W = 720
_STAGE_H = 1280


def engine_name() -> str:
    """Motor de avatar configurado (ffmpeg | wav2lip | sadtalker)."""
    return _ENGINE


def _resolve_ffmpeg() -> str:
    """Localiza o ffmpeg (PATH ou o binario empacotado pelo imageio-ffmpeg)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


_FFMPEG = _resolve_ffmpeg()


# ------------------------------------------------------------
# Foto do apresentador (guardada em storage/live/presenter/)
# ------------------------------------------------------------
def presenter_path() -> Path | None:
    """Retorna a foto do apresentador salva, se existir."""
    if not _PRESENTER_DIR.is_dir():
        return None
    for ext in _IMG_EXTS:
        candidate = _PRESENTER_DIR / f"presenter{ext}"
        if candidate.is_file():
            return candidate
    return None


def save_presenter(data: bytes, ext: str) -> Path:
    """Salva/atualiza a foto do apresentador. Mantem apenas uma foto."""
    ext = (ext or "").lower().strip()
    if not ext.startswith("."):
        ext = "." + ext
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in _IMG_EXTS:
        raise ValueError(f"Formato de imagem nao suportado: {ext}")

    _PRESENTER_DIR.mkdir(parents=True, exist_ok=True)
    # Remove fotos antigas (troca a foto do apresentador).
    for old in _PRESENTER_DIR.glob("presenter.*"):
        try:
            old.unlink()
        except Exception:
            pass

    out = _PRESENTER_DIR / f"presenter{ext}"
    out.write_bytes(data)
    return out


def has_presenter() -> bool:
    return presenter_path() is not None


# ------------------------------------------------------------
# Geracao do clipe do apresentador falando
# ------------------------------------------------------------
def render_clip(
    audio_path: str | os.PathLike,
    *,
    image_path: str | os.PathLike | None = None,
    engine: str | None = None,
) -> dict:
    """Gera um mp4 do apresentador falando a partir do audio + foto.

    Retorna {ok, video_rel, engine, note?} ou {ok: False, reason}.
    """
    audio = Path(audio_path)
    if not audio.is_file():
        return {"ok": False, "reason": "Audio da resposta nao encontrado."}

    image = Path(image_path) if image_path else presenter_path()
    if not image or not Path(image).is_file():
        return {
            "ok": False,
            "reason": "Sem foto do apresentador. Envie uma foto nos ajustes.",
        }

    _CLIP_DIR.mkdir(parents=True, exist_ok=True)
    eng = (engine or _ENGINE).strip().lower()

    if eng == "wav2lip":
        return _wav2lip(audio, image)
    if eng == "sadtalker":
        return _sadtalker(audio, image)
    return _ffmpeg_still(audio, image)


def _finish(out: Path, engine: str, note: str = "") -> dict:
    if not out.is_file() or out.stat().st_size == 0:
        return {"ok": False, "reason": "O video nao foi gerado.", "engine": engine}
    video_rel = os.path.relpath(out, _ATLAS_ROOT).replace("\\", "/")
    result = {"ok": True, "video_rel": video_rel, "engine": engine}
    if note:
        result["note"] = note
    return result


def _ffmpeg_still(audio: Path, image: Path, note: str = "") -> dict:
    """Baseline SEM placa: foto parada + audio -> mp4 vertical 9:16.

    Nao mexe a boca (isso e o Wav2Lip no G15), mas prova o pipeline
    inteiro: comentario -> IA -> voz -> VIDEO -> toca no palco.
    """
    out = _CLIP_DIR / f"clip_{uuid.uuid4().hex[:10]}.mp4"
    vf = (
        f"scale={_STAGE_W}:{_STAGE_H}:force_original_aspect_ratio=increase,"
        f"crop={_STAGE_W}:{_STAGE_H},format=yuv420p"
    )
    cmd = [
        _FFMPEG,
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        vf,
        "-shortest",
        str(out),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        return {"ok": False, "reason": f"Falha ao rodar ffmpeg: {exc}", "engine": "ffmpeg"}

    if proc.returncode != 0:
        tail = (proc.stderr or "")[-400:]
        return {"ok": False, "reason": f"ffmpeg falhou: {tail}", "engine": "ffmpeg"}

    return _finish(out, "ffmpeg", note)


def _wav2lip(audio: Path, image: Path) -> dict:
    """Lip-sync REAL com Wav2Lip (roda no G15 com placa NVIDIA).

    Configurar no G15 (variaveis de ambiente):
      ATLAS_WAV2LIP_DIR   -> pasta do repositorio Wav2Lip (com inference.py)
      ATLAS_WAV2LIP_PY    -> python.exe da venv do avatar (com torch cu128)
      ATLAS_WAV2LIP_CKPT  -> caminho do checkpoint (wav2lip_gan.pth)
    Se algo faltar, cai no motor ffmpeg (imagem parada) para nao travar a live.
    """
    repo = (os.getenv("ATLAS_WAV2LIP_DIR", "") or "").strip()
    py = (os.getenv("ATLAS_WAV2LIP_PY", "") or "").strip() or sys.executable
    ckpt = (os.getenv("ATLAS_WAV2LIP_CKPT", "") or "").strip()

    inference = Path(repo) / "inference.py" if repo else None
    if (
        not repo
        or inference is None
        or not inference.is_file()
        or not ckpt
        or not Path(ckpt).is_file()
    ):
        return _ffmpeg_still(
            audio,
            image,
            note="Wav2Lip nao configurado; usei imagem estatica. "
            "Instale no G15 e defina ATLAS_WAV2LIP_DIR/PY/CKPT.",
        )

    out = _CLIP_DIR / f"clip_{uuid.uuid4().hex[:10]}.mp4"
    cmd = [
        py,
        str(inference),
        "--checkpoint_path",
        ckpt,
        "--face",
        str(image),
        "--audio",
        str(audio),
        "--outfile",
        str(out),
        "--nosmooth",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        return _ffmpeg_still(
            audio, image, note=f"Wav2Lip falhou ({exc}); usei imagem estatica."
        )

    if proc.returncode != 0 or not out.is_file():
        tail = (proc.stderr or "")[-400:]
        return _ffmpeg_still(
            audio, image, note=f"Wav2Lip erro; usei imagem estatica. {tail}"
        )

    return _finish(out, "wav2lip")


def _sadtalker(audio: Path, image: Path) -> dict:
    """Reservado para o SadTalker (qualidade maior, mais lento).

    Por enquanto cai no ffmpeg; sera implementado quando/se escolhermos
    SadTalker no G15.
    """
    return _ffmpeg_still(
        audio, image, note="SadTalker ainda nao implementado; usei imagem estatica."
    )
