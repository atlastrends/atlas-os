import os
import re
import textwrap
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

# moviepy so e necessario na hora de gerar o video. Import protegido para
# permitir subir a API/painel em ambientes sem a stack de video instalada.
try:
    from moviepy.editor import ColorClip, TextClip, CompositeVideoClip, concatenate_videoclips
except Exception:  # noqa: BLE001
    ColorClip = TextClip = CompositeVideoClip = concatenate_videoclips = None

from app.core.database import get_db
from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    ContentStatusEnum,
    MarketplaceEnum,
)


router = APIRouter(prefix="/affiliate", tags=["Affiliate Video"])


class AffiliateVideoGenerateRequest(BaseModel):
    content_id: int
    duration_per_scene: float = 2.6
    width: int = 1080
    height: int = 1920
    fps: int = 30


def _safe_filename(value: str) -> str:
    value = value or "affiliate_video"
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value[:80] or "affiliate_video"


def _clean_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _wrap_limited(text: str, chars_per_line: int, max_lines: int) -> str:
    text = _clean_text(text)
    lines = textwrap.wrap(text, width=chars_per_line)

    if len(lines) <= max_lines:
        return "\n".join(lines)

    limited = lines[:max_lines]
    limited[-1] = limited[-1].rstrip(". ") + "..."
    return "\n".join(limited)


def _split_script_for_video(script: str, max_chars: int = 105, max_scenes: int = 6) -> List[str]:
    script = _clean_text(script)

    if not script:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", script)
    chunks = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        candidate = f"{current} {sentence}".strip()

        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    refined = []

    for chunk in chunks:
        if len(chunk) <= max_chars + 35:
            refined.append(chunk)
            continue

        parts = re.split(r",|;|:", chunk)
        buffer = ""

        for part in parts:
            part = part.strip()
            candidate = f"{buffer}, {part}".strip(", ").strip()

            if len(candidate) <= max_chars:
                buffer = candidate
            else:
                if buffer:
                    refined.append(buffer)
                buffer = part

        if buffer:
            refined.append(buffer)

    return refined[:max_scenes]


def _marketplace_theme(product: AffiliateProduct) -> Dict[str, Any]:
    if product.marketplace == MarketplaceEnum.AMAZON_US:
        return {
            "bg": (9, 12, 24),
            "card": (24, 31, 54),
            "accent": (255, 153, 0),
            "accent_dark": (180, 94, 0),
            "text": "white",
            "muted": "#D7DCE8",
            "badge": "AMAZON FIND",
            "cta": "COMMENT WANT",
            "cta_sub": "and I will send you the direct link",
            "disclaimer": "Amazon Associate disclosure applies.",
        }

    return {
        "bg": (9, 17, 14),
        "card": (20, 36, 30),
        "accent": (255, 153, 0),
        "accent_dark": (180, 94, 0),
        "text": "white",
        "muted": "#D7DCE8",
        "badge": "ACHADO AMAZON",
        "cta": "COMENTE QUERO",
        "cta_sub": "que eu te envio o link direto",
        "disclaimer": "Como Associado Amazon, posso ganhar com compras qualificadas.",
    }


def _text_clip(
    text: str,
    fontsize: int,
    color: str,
    box_width: int,
    box_height: Optional[int],
    duration: float,
    font: str = "DejaVu-Sans-Bold",
    align: str = "center",
):
    return TextClip(
        text,
        fontsize=fontsize,
        color=color,
        font=font,
        method="caption",
        size=(box_width, box_height),
        align=align,
    ).set_duration(duration)


def _make_badge(theme: Dict[str, Any], width: int, duration: float):
    badge_bg = (
        ColorClip(size=(560, 86), color=theme["accent"])
        .set_duration(duration)
        .set_position(("center", 130))
    )

    badge_text = (
        _text_clip(
            theme["badge"],
            fontsize=42,
            color="black",
            box_width=520,
            box_height=70,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", 142))
    )

    return [badge_bg, badge_text]


def _make_footer(theme: Dict[str, Any], width: int, height: int, duration: float):
    footer_bg = (
        ColorClip(size=(width, 190), color=theme["accent_dark"])
        .set_duration(duration)
        .set_position((0, height - 230))
    )

    footer_text = (
        _text_clip(
            theme["cta"],
            fontsize=58,
            color="white",
            box_width=width - 120,
            box_height=78,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", height - 215))
    )

    footer_sub = (
        _text_clip(
            theme["cta_sub"],
            fontsize=34,
            color="white",
            box_width=width - 140,
            box_height=62,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", height - 145))
    )

    return [footer_bg, footer_text, footer_sub]


def _make_opening_scene(
    product: AffiliateProduct,
    content: AffiliateContent,
    theme: Dict[str, Any],
    duration: float,
    width: int,
    height: int,
):
    bg = ColorClip(size=(width, height), color=theme["bg"]).set_duration(duration)

    card = (
        ColorClip(size=(width - 120, 900), color=theme["card"])
        .set_duration(duration)
        .set_position(("center", 360))
    )

    hook = _wrap_limited(content.hook_1 or product.title, chars_per_line=18, max_lines=4)
    product_title = _wrap_limited(product.title, chars_per_line=26, max_lines=3)

    hook_clip = (
        _text_clip(
            hook,
            fontsize=76,
            color=theme["text"],
            box_width=width - 190,
            box_height=430,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", 440))
    )

    product_clip = (
        _text_clip(
            product_title,
            fontsize=42,
            color=theme["muted"],
            box_width=width - 220,
            box_height=170,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", 920))
    )

    clips = [bg, card]
    clips += _make_badge(theme, width, duration)
    clips += [hook_clip, product_clip]
    clips += _make_footer(theme, width, height, duration)

    return CompositeVideoClip(clips, size=(width, height)).set_duration(duration)


def _make_body_scene(
    product: AffiliateProduct,
    body_text: str,
    scene_number: int,
    total_scenes: int,
    theme: Dict[str, Any],
    duration: float,
    width: int,
    height: int,
):
    bg = ColorClip(size=(width, height), color=theme["bg"]).set_duration(duration)

    top_title = _wrap_limited(product.title, chars_per_line=34, max_lines=2)
    body = _wrap_limited(body_text, chars_per_line=24, max_lines=5)

    top_clip = (
        _text_clip(
            top_title,
            fontsize=34,
            color=theme["muted"],
            box_width=width - 140,
            box_height=110,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", 165))
    )

    card = (
        ColorClip(size=(width - 120, 980), color=theme["card"])
        .set_duration(duration)
        .set_position(("center", 395))
    )

    body_clip = (
        _text_clip(
            body,
            fontsize=62,
            color=theme["text"],
            box_width=width - 190,
            box_height=680,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", 520))
    )

    progress_text = f"{scene_number}/{total_scenes}"

    progress_clip = (
        _text_clip(
            progress_text,
            fontsize=32,
            color="black",
            box_width=140,
            box_height=54,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position((width - 210, 305))
    )

    progress_bg = (
        ColorClip(size=(150, 60), color=theme["accent"])
        .set_duration(duration)
        .set_position((width - 215, 300))
    )

    clips = [bg, top_clip, card, progress_bg, progress_clip, body_clip]
    clips += _make_footer(theme, width, height, duration)

    return CompositeVideoClip(clips, size=(width, height)).set_duration(duration)


def _make_final_scene(
    product: AffiliateProduct,
    content: AffiliateContent,
    theme: Dict[str, Any],
    duration: float,
    width: int,
    height: int,
):
    bg = ColorClip(size=(width, height), color=theme["bg"]).set_duration(duration)

    price = product.price_text or ""
    title = _wrap_limited(product.title, chars_per_line=24, max_lines=3)

    card = (
        ColorClip(size=(width - 120, 1040), color=theme["card"])
        .set_duration(duration)
        .set_position(("center", 330))
    )

    cta_main = (
        _text_clip(
            theme["cta"],
            fontsize=86,
            color=theme["text"],
            box_width=width - 160,
            box_height=210,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", 450))
    )

    cta_sub = (
        _text_clip(
            theme["cta_sub"],
            fontsize=48,
            color=theme["muted"],
            box_width=width - 180,
            box_height=150,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", 670))
    )

    product_clip = (
        _text_clip(
            title,
            fontsize=42,
            color="white",
            box_width=width - 220,
            box_height=190,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", 920))
    )

    price_text = price if price else product.category or ""

    price_clip = (
        _text_clip(
            price_text,
            fontsize=46,
            color="white",
            box_width=width - 220,
            box_height=90,
            duration=duration,
            font="DejaVu-Sans-Bold",
        )
        .set_position(("center", 1125))
    )

    disclaimer = _wrap_limited(
        content.disclosure or theme["disclaimer"],
        chars_per_line=42,
        max_lines=2,
    )

    disclaimer_clip = (
        _text_clip(
            disclaimer,
            fontsize=26,
            color=theme["muted"],
            box_width=width - 160,
            box_height=80,
            duration=duration,
            font="DejaVu-Sans",
        )
        .set_position(("center", height - 180))
    )

    clips = [bg, card]
    clips += _make_badge(theme, width, duration)
    clips += [cta_main, cta_sub, product_clip, price_clip, disclaimer_clip]

    return CompositeVideoClip(clips, size=(width, height)).set_duration(duration)


@router.post("/video/generate")
def generate_affiliate_video(
    payload: AffiliateVideoGenerateRequest,
    db: Session = Depends(get_db),
):
    content = (
        db.query(AffiliateContent)
        .filter(AffiliateContent.id == payload.content_id)
        .first()
    )

    if not content:
        raise HTTPException(status_code=404, detail="Conteúdo não encontrado.")

    product = (
        db.query(AffiliateProduct)
        .filter(AffiliateProduct.id == content.product_id)
        .first()
    )

    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    current_status = (
        content.status.value
        if hasattr(content.status, "value")
        else str(content.status or "")
    )

    if current_status != ContentStatusEnum.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente conteudo aprovado pode gerar video."
            ),
        )

    theme = _marketplace_theme(product)

    script_chunks = _split_script_for_video(content.script, max_chars=105, max_scenes=5)

    scenes = []

    scenes.append(
        _make_opening_scene(
            product=product,
            content=content,
            theme=theme,
            duration=payload.duration_per_scene,
            width=payload.width,
            height=payload.height,
        )
    )

    total_body_scenes = len(script_chunks)

    for index, chunk in enumerate(script_chunks, start=1):
        scenes.append(
            _make_body_scene(
                product=product,
                body_text=chunk,
                scene_number=index,
                total_scenes=total_body_scenes,
                theme=theme,
                duration=payload.duration_per_scene,
                width=payload.width,
                height=payload.height,
            )
        )

    scenes.append(
        _make_final_scene(
            product=product,
            content=content,
            theme=theme,
            duration=payload.duration_per_scene,
            width=payload.width,
            height=payload.height,
        )
    )

    if not scenes:
        raise HTTPException(status_code=400, detail="Não há cenas para gerar vídeo.")

    final_clip = concatenate_videoclips(scenes, method="compose")

    output_dir = "/atlas/storage/affiliate_videos"
    os.makedirs(output_dir, exist_ok=True)

    filename = f"affiliate_content_{content.id}_{_safe_filename(product.asin)}.mp4"
    output_path = os.path.join(output_dir, filename)

    final_clip.write_videofile(
        output_path,
        fps=payload.fps,
        codec="libx264",
        audio=False,
        preset="medium",
        threads=2,
    )

    final_clip.close()

    for scene in scenes:
        scene.close()

    public_path = f"/storage/affiliate_videos/{filename}"

    return {
        "ok": True,
        "content_id": content.id,
        "product_id": product.id,
        "marketplace": product.marketplace.value if product.marketplace else None,
        "video_path": public_path,
        "filename": filename,
        "format": "9:16",
        "width": payload.width,
        "height": payload.height,
        "fps": payload.fps,
        "scenes": len(scenes),
        "layout": "conversion_short_safe_text_v1",
    }
