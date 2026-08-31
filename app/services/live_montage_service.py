# ============================================================
# ATLAS OS - services/live_montage_service.py
#
# "MONTADOR DE LIVE COM VIDEOS PRONTOS".
#
# Em vez de usar uma FOTO parada da apresentadora, esta montagem
# reaproveita os VIDEOS DE PRODUTO que o pipeline de afiliados JA gerou
# (storage/video_pipeline/outputs/*.mp4) - eles ja tem footage real,
# legendas e a NARRACAO falando do produto.
#
# A live vira uma CONCATENACAO desses videos, no formato de live, com a
# IA respondendo perguntas do "chat" entre um produto e outro. NAO
# aparece nenhum avatar: o que se ve na tela sao os proprios videos ja
# gerados (e, nas pontes de pergunta/abertura/encerramento, um QUADRO
# CONGELADO do proprio video com a legenda e a voz da IA por cima).
#
#   abertura -> [video do produto 1] -> pergunta/resposta ->
#   [video do produto 2] -> pergunta/resposta -> ... -> encerramento
#   (que ja volta ao 1o produto = loop invisivel)
#
# O resultado e salvo na MESMA pasta das outras lives (storage/live/videos)
# com um manifesto .json, entao a listagem e a transmissao ja funcionam.
# ============================================================

from __future__ import annotations

import html
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.services import live_brain_service as brain
from app.services import live_script_service as script
from app.services import live_video_service as v

# Reaproveita a configuracao/utilidades do montador padrao.
_ATLAS_ROOT = v._ATLAS_ROOT
_VIDEO_DIR = v._VIDEO_DIR                       # storage/live/videos (mesma das outras lives)
_BUILD_DIR = _ATLAS_ROOT / "storage" / "live" / "_montage"
_AFF_DIR = _ATLAS_ROOT / "storage" / "video_pipeline" / "outputs"
_DOCS_DIR = _ATLAS_ROOT / "docs"

_FFMPEG = v._FFMPEG
_W, _H, _FPS = v._W, v._H, v._FPS
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)


# ------------------------------------------------------------
# Leitura dos videos ja gerados (afiliados)
# ------------------------------------------------------------
def _safe_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _img_cache() -> dict:
    data = _safe_json(_DOCS_DIR / "_img_cache.json")
    return data if isinstance(data, dict) else {}


def _market_of(data: dict) -> str:
    mk = (data.get("marketplace_code") or data.get("market") or "").upper()
    return mk if mk in ("BR", "US") else ""


def _lang_of(data: dict) -> str:
    return script._norm_language(data.get("language") or "")


def _product_image(asin: str, platform: str = "amazon") -> str:
    if (platform or "").strip().lower() != "amazon":
        return ""
    asin = (asin or "").upper()
    if not asin:
        return ""
    cache = _img_cache()
    return cache.get(asin) or f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"


def list_sources(
    market: str = "",
    language: str = "",
    platform: str = "",
) -> list[dict]:
    """Lista os videos de produto JA gerados (afiliados) que podem virar live.

    market:   "" (todos) | "BR" | "US".
    language: "" (todos) | "pt" | "en".
    Retorna os mais novos primeiro.
    """
    if not _AFF_DIR.is_dir():
        return []

    want_mk = (market or "").upper()
    want_lang = script._norm_language(language) if language else ""
    want_platform = (platform or "").strip().lower()

    out: list[dict] = []
    for mp4 in sorted(_AFF_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        # Os arquivos ".live.mp4" sao a VERSAO DE LIVE do reels de mesmo nome.
        # Eles entram pelo reels irmao (abaixo), nunca como item separado.
        if mp4.name.endswith(".live.mp4"):
            continue
        try:
            if mp4.stat().st_size < 200 * 1024:  # ignora arquivos quebrados
                continue
        except Exception:
            continue

        stem = mp4.stem
        data = _safe_json(mp4.with_suffix(".json"))
        mk = _market_of(data)
        lang = _lang_of(data)
        source_platform = (data.get("platform") or "amazon").strip().lower()

        if want_mk and mk and mk != want_mk:
            continue
        if want_lang and lang and lang != want_lang:
            continue
        if want_platform and source_platform != want_platform:
            continue

        # Prefere a versao de LIVE (audio de apresentadora, sem gancho de
        # reels) quando ela existe. Assim a montagem usa o audio certo.
        live_mp4 = mp4.with_name(stem + ".live.mp4")
        has_live = live_mp4.is_file()
        video_file = live_mp4 if has_live else mp4

        asin = (data.get("asin") or "").upper()
        title = html.unescape((data.get("title") or stem).strip())
        out.append(
            {
                "id": stem,
                "title": title,
                "asin": asin,
                "market": mk,
                "language": lang,
                "category_label": data.get("category_label") or "",
                "affiliate_url": data.get("affiliate_url") or "",
                "platform": source_platform,
                "image": data.get("image_url") or _product_image(
                    asin, source_platform
                ),
                "video_rel": os.path.relpath(video_file, _ATLAS_ROOT).replace("\\", "/"),
                "size_mb": round(video_file.stat().st_size / (1024 * 1024), 1),
                "variant": "live" if has_live else "reel",
                "has_live": has_live,
            }
        )

    # Versoes de LIVE cujo reels .mp4 ja foi PURGADO (arquivo pesado apagado
    # depois de publicar): o .live.mp4 continua valendo para a montagem. Sem
    # isto o produto sumiria da live so por ter sido purgado -- exatamente o
    # que NAO queremos, ja que a versao de live e a que deve ser mantida.
    seen = {e["id"] for e in out}
    for live_mp4 in sorted(
        _AFF_DIR.glob("*.live.mp4"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        stem = live_mp4.name[: -len(".live.mp4")]
        if stem in seen:
            continue  # ja entrou pelo reels irmao acima
        if (_AFF_DIR / f"{stem}.mp4").is_file():
            continue  # ainda tem reels: tratado pelo loop de cima
        try:
            if live_mp4.stat().st_size < 200 * 1024:  # ignora arquivos quebrados
                continue
        except OSError:
            continue
        # Metadata: o sidecar do reels (.json) e MANTIDO no purge; se faltar,
        # cai no sidecar da propria live (.live.json).
        data = _safe_json(_AFF_DIR / f"{stem}.json") or _safe_json(
            live_mp4.with_suffix(".json")
        )
        mk = _market_of(data)
        lang = _lang_of(data)
        source_platform = (data.get("platform") or "amazon").strip().lower()
        if want_mk and mk and mk != want_mk:
            continue
        if want_lang and lang and lang != want_lang:
            continue
        if want_platform and source_platform != want_platform:
            continue
        asin = (data.get("asin") or "").upper()
        title = html.unescape((data.get("title") or stem).strip())
        seen.add(stem)
        out.append(
            {
                "id": stem,
                "title": title,
                "asin": asin,
                "market": mk,
                "language": lang,
                "category_label": data.get("category_label") or "",
                "affiliate_url": data.get("affiliate_url") or "",
                "platform": source_platform,
                "image": data.get("image_url") or _product_image(
                    asin, source_platform
                ),
                "video_rel": os.path.relpath(live_mp4, _ATLAS_ROOT).replace("\\", "/"),
                "size_mb": round(live_mp4.stat().st_size / (1024 * 1024), 1),
                "variant": "live",
                "has_live": True,
            }
        )
    return out


def _source_by_id(stem: str) -> dict | None:
    base = os.path.basename(stem)
    # Se vier o stem da live por engano, normaliza pro reels irmao.
    if base.endswith(".live"):
        base = base[: -len(".live")]
    mp4 = _AFF_DIR / f"{base}.mp4"
    live_mp4 = _AFF_DIR / f"{base}.live.mp4"
    # Aceita o produto se existir o reels OU a versao de live (o reels pode ter
    # sido PURGADO depois de publicar; a live continua servindo para montar).
    if not mp4.is_file() and not live_mp4.is_file():
        return None
    # Metadata: sidecar do reels (.json, mantido no purge) ou o da live (.live.json).
    data = _safe_json(mp4.with_suffix(".json"))
    if not data:
        data = _safe_json(live_mp4.with_suffix(".json"))

    # Prefere a versao de LIVE (com audio de apresentadora) quando existir.
    if live_mp4.is_file():
        live_data = _safe_json(live_mp4.with_suffix(".json"))
        video_file = live_mp4
        narration = (live_data.get("narration") or data.get("narration") or "").strip()
    else:
        video_file = mp4
        narration = (data.get("narration") or "").strip()

    asin = (data.get("asin") or "").upper()
    source_platform = (data.get("platform") or "amazon").strip().lower()
    return {
        "id": mp4.stem,
        "title": html.unescape((data.get("title") or mp4.stem).strip()),
        "asin": asin,
        "market": _market_of(data),
        "language": _lang_of(data),
        "affiliate_url": data.get("affiliate_url") or "",
        "platform": source_platform,
        "narration": narration,
        "image": data.get("image_url") or _product_image(
            asin, source_platform
        ),
        "path": video_file,
    }


# ------------------------------------------------------------
# Utilidades de midia (ffmpeg)
# ------------------------------------------------------------
def _media_info(path: Path) -> tuple[float, bool]:
    """Retorna (duracao_em_segundos, tem_audio) lendo o stderr do ffmpeg."""
    try:
        p = subprocess.run([_FFMPEG, "-i", str(path)], capture_output=True, text=True, timeout=60)
        err = p.stderr or ""
    except Exception:
        return (0.0, False)
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return (dur, " Audio:" in err)


def _normalize_product_clip(src: Path, out: Path, has_audio: bool) -> bool:
    """Reencoda o video do produto para o padrao da live (720x1280, 25fps,
    aac) para poder concatenar com as pontes. Garante SEMPRE 1 faixa de audio."""
    vf = (
        f"scale={_W}:{_H}:force_original_aspect_ratio=decrease,"
        f"pad={_W}:{_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={_FPS}"
    )
    common = [
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-ac", "2", "-movflags", "+faststart",
    ]
    if has_audio:
        cmd = [_FFMPEG, "-y", "-i", str(src), "-vf", vf, "-map", "0:v:0", "-map", "0:a:0", *common, str(out)]
    else:
        cmd = [
            _FFMPEG, "-y", "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vf, "-map", "0:v:0", "-map", "1:a:0", "-shortest", *common, str(out),
        ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception:
        return False
    return p.returncode == 0 and out.is_file() and out.stat().st_size > 0


def _extract_frame(src: Path, out_jpg: Path, at_seconds: float) -> bool:
    """Salva UM quadro do video (para servir de fundo congelado nas pontes)."""
    at = max(0.0, at_seconds)
    cmd = [_FFMPEG, "-y", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "3", str(out_jpg)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception:
        return False
    return p.returncode == 0 and out_jpg.is_file() and out_jpg.stat().st_size > 0


# ------------------------------------------------------------
# Pergunta simulada do "chat" + resposta da IA
# ------------------------------------------------------------
def _qa_pair(product: dict, language: str, persona: str, use_ai: bool) -> tuple[str, str]:
    language = script._norm_language(language)
    question = random.choice(script._qa_questions(language))
    answer = ""
    if use_ai:
        result = brain.generate(script._qa_prompt(product, question, language=language, words=26))
        answer = (result.get("text") or "").strip().strip('"').strip("'").strip() if result else ""
    if not answer:
        answer = script._fallback_qa_answer(product, language)
    return question, answer


def _qa_spoken(question: str, answer: str, language: str) -> str:
    if script._norm_language(language) == "en":
        return f"Someone in the chat just asked: {question} {answer}"
    return f"Alguém aqui no chat perguntou: {question} {answer}"


# ------------------------------------------------------------
# Banner da bio (mesma imagem da pagina de link) - usado como fundo da
# ABERTURA da live em vez de um quadro escurecido/tela escura.
# ------------------------------------------------------------
def _bio_banner_path(market: str) -> Path | None:
    name = "banner-us.jpg" if (market or "").upper() == "US" else "banner-br.jpg"
    path = _DOCS_DIR / name
    return path if path.is_file() else None


def _intro_scene(
    banner: Path | None,
    *,
    tag: str,
    caption: str,
    language: str,
    out_png: Path,
) -> Path:
    """Cena de ABERTURA da live: usa o BANNER da bio (a mesma imagem da
    pagina de link na bio) como pano de fundo em vez do quadro de video
    escurecido - fica com cara de MARCA logo de cara, nao de tela escura."""
    scene = v._gradient_bg()

    if banner and Path(banner).is_file():
        try:
            bimg = Image.open(banner).convert("RGB")
            # "contain": mostra o banner INTEIRO (nada de logo/texto cortado),
            # centralizado sobre o degrade da marca.
            fitted = v._fit_contain(bimg, _W - 72, int(_H * 0.40))
            x = (_W - fitted.width) // 2
            y = int(_H * 0.16)

            shadow = Image.new("RGBA", (_W, _H), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                (x - 16, y - 16, x + fitted.width + 16, y + fitted.height + 16),
                radius=24,
                fill=(0, 0, 0, 130),
            )
            scene = scene.convert("RGBA")
            scene.alpha_composite(shadow)
            scene = scene.convert("RGB")
            scene.paste(fitted, (x, y))
            banner_bottom = y + fitted.height
        except Exception:
            banner_bottom = int(_H * 0.16) + int(_H * 0.40)
    else:
        banner_bottom = int(_H * 0.16) + int(_H * 0.40)

    draw = ImageDraw.Draw(scene, "RGBA")

    # Selo AO VIVO (topo).
    live_txt = "AO VIVO" if language != "en" else "LIVE"
    bf = v._font(30, bold=True)
    v._rounded(draw, (28, 34, 210, 90), 28, v._LIVE_RED)
    draw.ellipse((52, 52, 74, 74), fill=v._WHITE)
    draw.text((88, 45), live_txt, font=bf, fill=v._WHITE)

    # Etiqueta central (ex.: "AO VIVO AGORA"), logo abaixo do banner.
    if tag:
        tf = v._font(26, bold=True)
        tw = draw.textlength(tag, font=tf)
        y_tag = banner_bottom + 30
        v._rounded(draw, ((_W - tw) / 2 - 24, y_tag, (_W + tw) / 2 + 24, y_tag + 58), 26, (124, 92, 255, 235))
        draw.text(((_W - tw) / 2, y_tag + 11), tag, font=tf, fill=v._WHITE)

    # Legenda (rodape) = o que esta sendo falado.
    v._draw_caption(draw, caption, language)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    scene.save(out_png, "PNG")
    return out_png


# ------------------------------------------------------------
# CENA de PONTE (abertura / pergunta / encerramento) - SEM avatar.
# Fundo = quadro congelado do proprio video + legenda + selo AO VIVO.
# ------------------------------------------------------------
def _bridge_scene(
    bg_frame: Path | None,
    *,
    tag: str,
    question: str,
    caption: str,
    language: str,
    out_png: Path,
) -> Path:
    if bg_frame and Path(bg_frame).is_file():
        try:
            scene = v._fit_cover(Image.open(bg_frame).convert("RGB"), _W, _H)
            # Desfoca forte: o quadro vira so um FUNDO ambiente do produto.
            # Assim o QR/legendas queimadas do video original nao competem
            # com o balao da pergunta e a legenda da ponte.
            scene = scene.filter(ImageFilter.GaussianBlur(22))
        except Exception:
            scene = v._gradient_bg()
    else:
        scene = v._gradient_bg()

    # Escurece a imagem toda para a legenda/pergunta lerem bem.
    scene = scene.convert("RGBA")
    scene.alpha_composite(Image.new("RGBA", (_W, _H), (6, 4, 14, 185)))
    scene = scene.convert("RGB")
    draw = ImageDraw.Draw(scene, "RGBA")

    # Selo AO VIVO + plataforma (topo).
    live_txt = "AO VIVO" if language != "en" else "LIVE"
    bf = v._font(30, bold=True)
    v._rounded(draw, (28, 34, 210, 90), 28, v._LIVE_RED)
    draw.ellipse((52, 52, 74, 74), fill=v._WHITE)
    draw.text((88, 45), live_txt, font=bf, fill=v._WHITE)
    pf = v._font(26, bold=True)
    ptxt = "AMAZON"
    pw = draw.textlength(ptxt, font=pf)
    v._rounded(draw, (_W - 40 - pw - 40, 34, _W - 28, 88), 26, (255, 255, 255, 40))
    draw.text((_W - 40 - pw - 20, 46), ptxt, font=pf, fill=v._WHITE)

    # Etiqueta central (ex.: "PERGUNTA DO CHAT").
    if tag:
        tf = v._font(26, bold=True)
        tw = draw.textlength(tag, font=tf)
        v._rounded(draw, ((_W - tw) / 2 - 24, 150, (_W + tw) / 2 + 24, 208), 26, (124, 92, 255, 235))
        draw.text(((_W - tw) / 2, 161), tag, font=tf, fill=v._WHITE)

    # Balao da pergunta (estilo chat).
    if question:
        qf = v._font(30, bold=True)
        qlines = v._wrap(draw, question, qf, _W - 150)[:3]
        bh = len(qlines) * 40 + 40
        top = 244
        v._rounded(draw, (60, top, _W - 60, top + bh), 24, (255, 255, 255, 240))
        yy = top + 18
        for ln in qlines:
            lw = draw.textlength(ln, font=qf)
            draw.text(((_W - lw) / 2, yy), ln, font=qf, fill=(22, 16, 42))
            yy += 40

    # Legenda (rodape) = o que esta sendo falado.
    v._draw_caption(draw, caption, language)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    scene.save(out_png, "PNG")
    return out_png


# ------------------------------------------------------------
# API principal: monta a live a partir dos videos ja gerados
# ------------------------------------------------------------
def build_live_from_videos(
    video_ids: list[str] | None = None,
    *,
    market: str = "",
    language: str = "pt",
    platform: str = "",
    persona: str = "",
    use_ai: bool = True,
    qa: bool = True,
    add_intro: bool = True,
    max_products: int = 0,
    progress=None,
) -> dict:
    """Concatena os videos de produto ja gerados no formato de live.

    video_ids: ids (nome do arquivo sem extensao) na ORDEM desejada.
               Se vazio, usa os primeiros da plataforma (market/language).
    progress(done, total, label) e' chamado a cada etapa (opcional).
    """
    language = script._norm_language(language)

    # Resolve a lista de produtos (na ordem pedida).
    products: list[dict] = []
    if video_ids:
        for vid in video_ids:
            src = _source_by_id(vid)
            if src and src["path"].is_file():
                products.append(src)
    else:
        for meta in list_sources(
            market=market,
            language=language,
            platform=platform,
        ):
            src = _source_by_id(meta["id"])
            if src and src["path"].is_file():
                products.append(src)
    if max_products and max_products > 0:
        products = products[:max_products]

    if not products:
        return {"ok": False, "reason": "Nenhum video de produto encontrado para montar a live."}

    mk = (market or products[0].get("market") or "").upper()
    source_platform = (
        platform or products[0].get("platform") or "amazon"
    ).strip().lower()
    platform_name = "Shopee" if source_platform == "shopee" else "Amazon"

    job = f"m{int(time.time())}"
    job_dir = _BUILD_DIR / job
    job_dir.mkdir(parents=True, exist_ok=True)
    _VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    # Quantidade aproximada de etapas para a barra de progresso.
    total_steps = (
        len(products) * (2 if qa else 1)
        + max(0, len(products) - 1)  # pontes de transicao entre produtos
        + (1 if add_intro else 0)
        + 1
    )
    step = 0

    def _tick(label: str) -> None:
        nonlocal step
        step += 1
        if progress:
            try:
                progress(step, total_steps, label)
            except Exception:
                pass

    clips: list[Path] = []
    manifest_blocks: list[dict] = []
    start = 0

    def _add_block(kind: str, text: str, seconds: int, product: dict | None) -> None:
        nonlocal start
        manifest_blocks.append(
            {"kind": kind, "text": text, "seconds": int(seconds), "start": start, "product": product}
        )
        start += int(seconds)

    # Prepara: normaliza cada produto e extrai um quadro para as pontes.
    prepared: list[dict] = []
    for i, prod in enumerate(products):
        _tick("produto")
        dur, has_audio = _media_info(prod["path"])
        norm = job_dir / f"prod_{i:03d}.mp4"
        if not _normalize_product_clip(prod["path"], norm, has_audio):
            continue
        frame = job_dir / f"frame_{i:03d}.jpg"
        at = (dur * 0.6) if dur > 2 else 0.5
        if not _extract_frame(prod["path"], frame, at):
            frame = None
        seconds = int(round(dur)) if dur > 0 else 30
        prepared.append(
            {
                "prod": prod,
                "clip": norm,
                "frame": frame,
                "seconds": seconds,
            }
        )

    if not prepared:
        v._cleanup_dir(job_dir)
        return {"ok": False, "reason": "Nao consegui preparar os videos (reencode falhou)."}

    def _product_card(prod: dict) -> dict:
        return {
            "title": prod.get("title", ""),
            "image": prod.get("image", ""),
            "url": prod.get("affiliate_url", ""),
            "price": "",
        }

    # ---- ABERTURA (fundo = banner da bio, marca desde o 1o segundo) ----
    if add_intro:
        intro_txt = script._intro_text(platform_name, language, len(prepared))
        scene = job_dir / "intro.png"
        tag = "AO VIVO AGORA" if language != "en" else "LIVE NOW"
        banner = _bio_banner_path(mk)
        _intro_scene(banner, tag=tag, caption=intro_txt, language=language, out_png=scene)
        clip = job_dir / "intro.mp4"
        if v._render_block(intro_txt, scene, language, clip, script.estimate_seconds(intro_txt, language)):
            clips.append(clip)
            _add_block("intro", intro_txt, script.estimate_seconds(intro_txt, language), None)

    # ---- PRODUTOS + PERGUNTAS + TRANSICOES NATURAIS ----
    last = len(prepared) - 1
    for i, item in enumerate(prepared):
        prod = item["prod"]
        clips.append(item["clip"])
        _add_block("product", prod.get("narration", ""), item["seconds"], _product_card(prod))

        if qa:
            _tick("pergunta")
            question, answer = _qa_pair(prod, language, persona, use_ai)
            spoken = _qa_spoken(question, answer, language)
            scene = job_dir / f"qa_{len(clips):03d}.png"
            tag = "PERGUNTA DO CHAT" if language != "en" else "QUESTION FROM CHAT"
            _bridge_scene(item["frame"], tag=tag, question=question, caption=answer, language=language, out_png=scene)
            clip = job_dir / f"qa_{len(clips):03d}.mp4"
            if v._render_block(spoken, scene, language, clip, script.estimate_seconds(spoken, language)):
                clips.append(clip)
                _add_block("qa", spoken, script.estimate_seconds(spoken, language), _product_card(prod))

        # Transicao natural pro PROXIMO produto (evita cortar seco de um
        # video pro outro - a IA escreve uma ponte falada e cheia de energia).
        if i < last:
            _tick("transicao")
            nxt = prepared[i + 1]
            trans_txt = script._transition_text(prod, nxt["prod"], language, persona=persona, use_ai=use_ai)
            scene = job_dir / f"trans_{len(clips):03d}.png"
            tag = "A SEGUIR" if language != "en" else "UP NEXT"
            _bridge_scene(nxt["frame"], tag=tag, question="", caption=trans_txt, language=language, out_png=scene)
            clip = job_dir / f"trans_{len(clips):03d}.mp4"
            if v._render_block(trans_txt, scene, language, clip, script.estimate_seconds(trans_txt, language)):
                clips.append(clip)
                _add_block("transition", trans_txt, script.estimate_seconds(trans_txt, language), _product_card(nxt["prod"]))

    # ---- ENCERRAMENTO (ja volta ao 1o produto = loop invisivel) ----
    outro_txt = script._outro_text(language)
    scene = job_dir / "outro.png"
    tag = "VOLTANDO AO INICIO" if language != "en" else "BACK TO THE START"
    _bridge_scene(prepared[0]["frame"], tag=tag, question="", caption=outro_txt, language=language, out_png=scene)
    clip = job_dir / "outro.mp4"
    if v._render_block(outro_txt, scene, language, clip, script.estimate_seconds(outro_txt, language)):
        clips.append(clip)
        _add_block("outro", outro_txt, script.estimate_seconds(outro_txt, language), _product_card(prepared[0]["prod"]))

    _tick("juntando")

    if not clips:
        v._cleanup_dir(job_dir)
        return {"ok": False, "reason": "Nenhum clipe foi gerado."}

    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"live_montage_{source_platform}_{mk or 'ALL'}_{stamp}.mp4"
    out_mp4 = _VIDEO_DIR / name
    if not v._concat(clips, out_mp4):
        v._cleanup_dir(job_dir)
        return {"ok": False, "reason": "Falha ao juntar os videos."}

    manifest = {
        "video": name,
        "source": "montage",
        "platform": source_platform,
        "platform_name": f"{platform_name} (vídeos prontos)",
        "market": mk,
        "language": language,
        "created": stamp,
        "total_seconds": start,
        "product_count": len(prepared),
        "recap_lines": script.recap_lines(language),
        "blocks": manifest_blocks,
    }
    out_mp4.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    v._cleanup_dir(job_dir)

    if progress:
        try:
            progress(total_steps, total_steps, "done")
        except Exception:
            pass

    return {
        "ok": True,
        "video": name,
        "video_rel": os.path.relpath(out_mp4, _ATLAS_ROOT).replace("\\", "/"),
        "total_seconds": start,
        "product_count": len(prepared),
        "blocks": len(manifest_blocks),
    }
