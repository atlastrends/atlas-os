# ============================================================
# ATLAS OS - services/live_video_service.py
#
# "MONTADOR" da live gravada. Pega o ROTEIRO (live_script_service) e
# monta UM video longo .mp4, pronto para transmitir como se fosse live:
#
#   para cada bloco:
#     1) compoe a CENA (imagem 720x1280): apresentadora + card do produto
#        + legenda da fala + selo AO VIVO   (Pillow)
#     2) gera a VOZ da fala (Edge TTS, via live_brain_service.speak)
#     3) junta imagem + voz num clipe .mp4  (ffmpeg)
#   depois CONCATENA todos os clipes num video unico (ffmpeg concat).
#
# Tambem grava um MANIFESTO .json (o que aparece em cada segundo) que a
# tela de Live usa para mostrar a legenda/produto e as frases de recomeco.
#
# Roda em QUALQUER PC (sem placa). No G15, o motor de avatar (Wav2Lip)
# pode substituir a imagem parada por boca mexendo numa etapa futura.
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.services import live_avatar_service as avatar
from app.services import live_brain_service as brain
from app.services import live_script_service as script

_ATLAS_ROOT = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
_VIDEO_DIR = _ATLAS_ROOT / "storage" / "live" / "videos"
_BUILD_DIR = _ATLAS_ROOT / "storage" / "live" / "_build"
_IMGCACHE_DIR = _ATLAS_ROOT / "storage" / "live" / "_imgcache"

_W, _H = 720, 1280
_FPS = 25
_FFMPEG = avatar._FFMPEG

# Cores (estilo estudio escuro).
_BG_TOP = (27, 16, 48)      # roxo escuro
_BG_BOTTOM = (11, 7, 22)    # quase preto
_ACCENT = (124, 92, 255)    # roxo vibrante
_LIVE_RED = (233, 45, 66)
_WHITE = (245, 245, 250)
_MUTED = (180, 180, 200)


# ------------------------------------------------------------
# Fontes
# ------------------------------------------------------------
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold
        else ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ------------------------------------------------------------
# Utilidades de desenho
# ------------------------------------------------------------
def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _gradient_bg() -> Image.Image:
    img = Image.new("RGB", (_W, _H), _BG_BOTTOM)
    draw = ImageDraw.Draw(img)
    for y in range(_H):
        t = y / (_H - 1)
        r = int(_BG_TOP[0] + (_BG_BOTTOM[0] - _BG_TOP[0]) * t)
        g = int(_BG_TOP[1] + (_BG_BOTTOM[1] - _BG_TOP[1]) * t)
        b = int(_BG_TOP[2] + (_BG_BOTTOM[2] - _BG_TOP[2]) * t)
        draw.line([(0, y), (_W, y)], fill=(r, g, b))
    return img


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _fit_contain(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    return img


def _download_image(url: str) -> Path | None:
    url = (url or "").strip()
    if not url.startswith("http"):
        return None
    _IMGCACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    dest = _IMGCACHE_DIR / f"{key}.img"
    if dest.is_file() and dest.stat().st_size > 512:
        return dest
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read()
        if len(data) < 512:
            return None
        dest.write_bytes(data)
        return dest
    except Exception:
        return None


def _rounded(draw: ImageDraw.ImageDraw, box, radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


# ------------------------------------------------------------
# Composicao da CENA (uma imagem por bloco)
# ------------------------------------------------------------
def _scene_image(
    block: dict,
    presenter: Path | None,
    idx: int,
    total: int,
    platform_name: str,
    language: str,
    out_png: Path,
) -> Path:
    scene = _gradient_bg()

    # Apresentadora ocupa a metade de cima (cover), com escurecimento suave.
    if presenter and Path(presenter).is_file():
        try:
            pimg = Image.open(presenter).convert("RGB")
            top_h = int(_H * 0.60)
            cover = _fit_cover(pimg, _W, top_h)
            scene.paste(cover, (0, 0))
            # Scrim (degrade preto) na base da foto para o texto ler bem.
            scrim = Image.new("L", (_W, top_h), 0)
            sd = ImageDraw.Draw(scrim)
            for y in range(top_h):
                a = int(220 * max(0.0, (y - top_h * 0.55) / (top_h * 0.45)))
                sd.line([(0, y), (_W, y)], fill=min(255, a))
            black = Image.new("RGB", (_W, top_h), (5, 3, 12))
            scene.paste(black, (0, 0), scrim)
        except Exception:
            pass

    draw = ImageDraw.Draw(scene, "RGBA")

    # --- Selo AO VIVO + plataforma (topo) ---
    live_txt = "AO VIVO" if language != "en" else "LIVE"
    bf = _font(30, bold=True)
    _rounded(draw, (28, 34, 210, 90), 28, _LIVE_RED)
    draw.ellipse((52, 52, 74, 74), fill=_WHITE)
    draw.text((88, 45), live_txt, font=bf, fill=_WHITE)
    pf = _font(26, bold=True)
    ptxt = platform_name.upper()
    pw = draw.textlength(ptxt, font=pf)
    _rounded(draw, (_W - 40 - pw - 40, 34, _W - 28, 88), 26, (255, 255, 255, 40))
    draw.text((_W - 40 - pw - 20, 46), ptxt, font=pf, fill=_WHITE)

    kind = block.get("kind")
    product = block.get("product") or {}

    if kind == "product" and product:
        _draw_product_card(draw, scene, product, language)
    else:
        _draw_headline(draw, block, language)

    # --- Legenda da fala (rodape) ---
    _draw_caption(draw, block.get("text", ""), language)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    scene.save(out_png, "PNG")
    return out_png


def _draw_product_card(draw: ImageDraw.ImageDraw, scene: Image.Image, product: dict, language: str) -> None:
    card_top = int(_H * 0.62)
    card = (28, card_top, _W - 28, card_top + 300)
    _rounded(draw, card, 28, (18, 14, 32, 235))
    _rounded(draw, (card[0], card[1], card[0] + 8, card[3]), 8, _ACCENT)

    # Imagem do produto (esquerda).
    thumb_box = (52, card_top + 30, 52 + 220, card_top + 30 + 220)
    img_path = _download_image(product.get("image", ""))
    placed = False
    if img_path:
        try:
            pi = Image.open(img_path).convert("RGB")
            white = Image.new("RGB", (220, 220), (255, 255, 255))
            fitted = _fit_contain(pi, 210, 210)
            wx = (220 - fitted.width) // 2
            wy = (220 - fitted.height) // 2
            white.paste(fitted, (wx, wy))
            mask = Image.new("L", (220, 220), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, 220, 220), radius=18, fill=255)
            scene.paste(white, (thumb_box[0], thumb_box[1]), mask)
            placed = True
        except Exception:
            placed = False
    if not placed:
        _rounded(draw, thumb_box, 18, (255, 255, 255, 30))
        draw.text((thumb_box[0] + 60, thumb_box[1] + 90), "IMG", font=_font(30, bold=True), fill=_MUTED)

    # Texto (direita).
    tx = thumb_box[2] + 28
    tw = card[2] - tx - 24
    title = (product.get("title") or "").strip()
    tf = _font(32, bold=True)
    lines = _wrap(draw, title, tf, tw)[:3]
    ty = card_top + 34
    for ln in lines:
        draw.text((tx, ty), ln, font=tf, fill=_WHITE)
        ty += 40

    price = (product.get("price") or "").strip()
    if price:
        prf = _font(34, bold=True)
        pw = draw.textlength(price, font=prf)
        _rounded(draw, (tx, ty + 6, tx + pw + 36, ty + 60), 26, _ACCENT)
        draw.text((tx + 18, ty + 12), price, font=prf, fill=_WHITE)
        ty += 74

    cta = "Link na descricao" if language != "en" else "Link in description"
    draw.text((tx, ty + 8), "\u2192 " + cta, font=_font(28, bold=True), fill=(200, 190, 255))


def _draw_headline(draw: ImageDraw.ImageDraw, block: dict, language: str) -> None:
    kind = block.get("kind")
    if kind == "outro":
        head = "OBRIGADO!" if language != "en" else "THANK YOU!"
    else:
        head = "OFERTAS AO VIVO" if language != "en" else "LIVE DEALS"
    hf = _font(66, bold=True)
    hw = draw.textlength(head, font=hf)
    y = int(_H * 0.66)
    draw.text(((_W - hw) / 2, y), head, font=hf, fill=_WHITE)
    sub = "Toque no link da descricao" if language != "en" else "Tap the link in the description"
    sf = _font(30)
    sw = draw.textlength(sub, font=sf)
    draw.text(((_W - sw) / 2, y + 84), sub, font=sf, fill=_MUTED)


def _draw_caption(draw: ImageDraw.ImageDraw, text: str, language: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    cf = _font(30)
    max_w = _W - 80
    lines = _wrap(draw, text, cf, max_w)[:3]
    line_h = 40
    box_h = line_h * len(lines) + 32
    top = _H - box_h - 30
    _rounded(draw, (28, top, _W - 28, top + box_h), 22, (0, 0, 0, 150))
    y = top + 16
    for ln in lines:
        draw.text((44, y), ln, font=cf, fill=_WHITE)
        y += line_h


# ------------------------------------------------------------
# Render de UM bloco (imagem + voz -> mp4 padronizado)
# ------------------------------------------------------------
def _silent_audio(seconds: int, out_path: Path) -> bool:
    cmd = [
        _FFMPEG, "-y", "-f", "lavfi", "-i",
        f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(max(1, seconds)), "-c:a", "aac", "-b:a", "128k", str(out_path),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode == 0 and out_path.is_file()
    except Exception:
        return False


def _render_block(text: str, scene_png: Path, language: str, out_mp4: Path, fallback_seconds: int) -> bool:
    """Gera voz da fala e junta com a cena num mp4 padronizado (para concatenar)."""
    # 1) Voz (Edge TTS). Se falhar, usa audio silencioso do tamanho estimado.
    audio_path: Path | None = None
    spoken = brain.speak(text, language=language)
    if spoken.get("ok") and spoken.get("audio_path"):
        audio_path = Path(spoken["audio_path"])
    else:
        silent = out_mp4.with_suffix(".silent.m4a")
        if _silent_audio(fallback_seconds, silent):
            audio_path = silent
    if not audio_path or not audio_path.is_file():
        return False

    # 2) Imagem parada + voz -> mp4 com parametros FIXOS (concat -c copy depois).
    cmd = [
        _FFMPEG, "-y",
        "-loop", "1", "-i", str(scene_png),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-r", str(_FPS), "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-vf", f"scale={_W}:{_H},setsar=1",
        "-shortest", "-movflags", "+faststart",
        str(out_mp4),
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except Exception:
        return False
    return p.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 0


# ------------------------------------------------------------
# Concatenacao dos blocos
# ------------------------------------------------------------
def _concat(mp4_list: list[Path], out_mp4: Path) -> bool:
    if not mp4_list:
        return False
    listfile = out_mp4.with_suffix(".list.txt")
    lines = ["file '" + str(p).replace("\\", "/") + "'" for p in mp4_list]
    listfile.write_text("\n".join(lines), encoding="utf-8")

    base = [_FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listfile)]
    # Tenta sem reencode (rapido). Se falhar, reencoda (robusto).
    for tail in (
        ["-c", "copy", "-movflags", "+faststart", str(out_mp4)],
        ["-c:v", "libx264", "-preset", "veryfast", "-r", str(_FPS),
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
         "-ac", "2", "-movflags", "+faststart", str(out_mp4)],
    ):
        try:
            p = subprocess.run(base + tail, capture_output=True, text=True, timeout=1800)
        except Exception:
            continue
        if p.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 0:
            try:
                listfile.unlink()
            except Exception:
                pass
            return True
    return False


# ------------------------------------------------------------
# API principal: monta a live gravada inteira
# ------------------------------------------------------------
def build_live(
    platform: str,
    *,
    market: str = "",
    language: str = "pt",
    persona: str = "",
    seconds_per_product: int = 30,
    max_products: int = 0,
    use_ai: bool = True,
    progress=None,
) -> dict:
    """Monta o video longo da live gravada de uma plataforma.

    progress(done, total, label) e' chamado a cada bloco (opcional).
    Retorna {ok, video_rel, manifest_rel, total_seconds, product_count, ...}.
    """
    roteiro = script.build_script(
        platform,
        market=market,
        language=language,
        persona=persona,
        seconds_per_product=seconds_per_product,
        max_products=max_products,
        use_ai=use_ai,
    )
    if not roteiro.get("ok"):
        return {"ok": False, "reason": roteiro.get("reason", "Nao consegui montar o roteiro.")}

    blocks = roteiro["blocks"]
    presenter = avatar.presenter_path()
    platform_name = roteiro.get("platform_name", platform.title())
    language = roteiro["language"]

    job = uuid.uuid4().hex[:10]
    job_dir = _BUILD_DIR / job
    job_dir.mkdir(parents=True, exist_ok=True)
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    clips: list[Path] = []
    manifest_blocks: list[dict] = []
    start = 0
    total = len(blocks)

    for i, block in enumerate(blocks):
        if progress:
            try:
                progress(i, total, block.get("kind", ""))
            except Exception:
                pass

        scene_png = job_dir / f"scene_{i:03d}.png"
        _scene_image(block, presenter, i, total, platform_name, language, scene_png)

        clip_mp4 = job_dir / f"block_{i:03d}.mp4"
        fallback_s = int(block.get("seconds", seconds_per_product)) or seconds_per_product
        ok = _render_block(block.get("text", ""), scene_png, language, clip_mp4, fallback_s)
        if not ok:
            continue
        clips.append(clip_mp4)

        secs = int(block.get("seconds", 0)) or fallback_s
        manifest_blocks.append(
            {
                "kind": block.get("kind"),
                "text": block.get("text", ""),
                "seconds": secs,
                "start": start,
                "product": block.get("product"),
            }
        )
        start += secs

    if not clips:
        return {"ok": False, "reason": "Nenhum bloco de video foi gerado."}

    stamp = time.strftime("%Y%m%d_%H%M%S")
    mk = (market or "").upper()
    name = f"live_{platform}_{mk or 'ALL'}_{stamp}.mp4"
    out_mp4 = _VIDEO_DIR / name
    if not _concat(clips, out_mp4):
        return {"ok": False, "reason": "Falha ao juntar os clipes."}

    manifest = {
        "video": name,
        "platform": platform,
        "platform_name": platform_name,
        "market": mk,
        "language": language,
        "created": stamp,
        "total_seconds": start,
        "product_count": roteiro.get("product_count", 0),
        "recap_lines": roteiro.get("recap_lines", []),
        "blocks": manifest_blocks,
    }
    manifest_path = out_mp4.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Limpa os arquivos temporarios do job (cenas e clipes de bloco).
    _cleanup_dir(job_dir)

    if progress:
        try:
            progress(total, total, "done")
        except Exception:
            pass

    video_rel = os.path.relpath(out_mp4, _ATLAS_ROOT).replace("\\", "/")
    manifest_rel = os.path.relpath(manifest_path, _ATLAS_ROOT).replace("\\", "/")
    return {
        "ok": True,
        "video": name,
        "video_rel": video_rel,
        "manifest_rel": manifest_rel,
        "total_seconds": start,
        "product_count": roteiro.get("product_count", 0),
        "blocks": len(manifest_blocks),
    }


def _cleanup_dir(path: Path) -> None:
    try:
        for child in path.glob("*"):
            try:
                child.unlink()
            except Exception:
                pass
        path.rmdir()
    except Exception:
        pass


# ------------------------------------------------------------
# Listagem dos videos ja montados (para a tela de Live)
# ------------------------------------------------------------
def list_recorded() -> list[dict]:
    """Lista os videos de live ja montados (mais novos primeiro)."""
    if not _VIDEO_DIR.is_dir():
        return []
    out: list[dict] = []
    for mp4 in sorted(_VIDEO_DIR.glob("live_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = {}
        mj = mp4.with_suffix(".json")
        if mj.is_file():
            try:
                meta = json.loads(mj.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        out.append(
            {
                "video": mp4.name,
                "url": f"/api/live/recorded/{mp4.name}",
                "size": mp4.stat().st_size,
                "platform": meta.get("platform", ""),
                "platform_name": meta.get("platform_name", ""),
                "market": meta.get("market", ""),
                "total_seconds": meta.get("total_seconds", 0),
                "product_count": meta.get("product_count", 0),
                "created": meta.get("created", ""),
            }
        )
    return out


def recorded_path(name: str) -> Path | None:
    """Caminho seguro de um video montado (para servir/transmitir)."""
    safe = os.path.basename(name)
    if not safe.endswith(".mp4"):
        return None
    path = (_VIDEO_DIR / safe).resolve()
    if _VIDEO_DIR.resolve() not in path.parents:
        return None
    return path if path.is_file() else None
