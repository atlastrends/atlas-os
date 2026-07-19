from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urlparse
import argparse
import asyncio
import csv
import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import uuid

import requests

# Importações do novo motor de vídeo autorizado
from app.automation.authorized_broll_renderer import (
    BrollError,
    make_story,
    narration_from_story,
    render_authorized_video,
)

WIDTH = 1080
HEIGHT = 1920
FPS = 30

ROOT = Path(
    os.getenv("ATLAS_ROOT", "/atlas")
).resolve()

if not (ROOT / "app").exists():
    ROOT = Path.cwd().resolve()

STORAGE = ROOT / "storage"
AMAZON_STORAGE = STORAGE / "amazon"
IMPORT_DIRECTORY = AMAZON_STORAGE / "imports"
SEED_PATH = AMAZON_STORAGE / "seed_terms.json"

VIDEO_STORAGE = STORAGE / "video_pipeline"
OUTPUT_DIRECTORY = VIDEO_STORAGE / "outputs"
WORK_DIRECTORY = VIDEO_STORAGE / "work"

APPROVAL_DIRECTORY = STORAGE / "approval"
PENDING_DIRECTORY = APPROVAL_DIRECTORY / "pending"
PROCESSED_DIRECTORY = APPROVAL_DIRECTORY / "processed"
FAILED_DIRECTORY = APPROVAL_DIRECTORY / "failed"

STATE_PATH = VIDEO_STORAGE / "pipeline_state.json"
LOG_PATH = VIDEO_STORAGE / "pipeline.jsonl"

MARKETS = {
    "BR": {
        "marketplace": "www.amazon.com.br",
        "domain": "amazon.com.br",
        "partner_tag": "achadosatlasb-20",
        "language": "pt-BR",
        "voice": "pt-BR-FranciscaNeural",
        "currency": "BRL",
        "search_index": "All",
    },
    "US": {
        "marketplace": "www.amazon.com",
        "domain": "amazon.com",
        "partner_tag": "atlasfindsus-20",
        "language": "en-US",
        "voice": "en-US-JennyNeural",
        "currency": "USD",
        "search_index": "All",
    },
}

SERVICE_MODULES = (
    "app.services.amazon_catalog",
    "app.services.amazon_catalog_service",
    "app.services.amazon_service",
    "app.integrations.amazon",
)

class PipelineError(RuntimeError):
    pass


@dataclass
class Product:
    marketplace_code: str
    asin: str
    title: str
    price_display: str
    image_url: str
    detail_url: str
    source: str
    score: float = 0.0
    brand: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    rating: float | None = None
    review_count: int | None = None
    discount_percent: int | None = None
    currency: str = ""
    category: str = ""
    category_label: str = ""


# Nomes amigaveis das categorias (slug -> rotulo exibido no painel).
CATEGORY_LABELS: dict[str, str] = {
    "electronics": "Eletronicos",
    "kitchen": "Cozinha",
    "home": "Casa",
    "beauty": "Beleza",
    "toys": "Brinquedos",
    "videogames": "Games",
    "sports": "Esportes",
    "pet-supplies": "Pet",
    "hpc": "Saude",
    "office-products": "Escritorio",
}


def _category_of(item: dict[str, Any]) -> tuple[str, str]:
    """Descobre (slug, rotulo) da categoria de um produto importado."""
    slug = str(item.get("category") or "").strip().lower()

    if not slug:
        # Compatibilidade: extrai de source tipo "movers_electronics".
        source = str(item.get("source") or "")
        if "_" in source:
            slug = source.split("_", 1)[1].strip().lower()

    if not slug:
        slug = "outros"

    label = (
        str(item.get("category_label") or "").strip()
        or CATEGORY_LABELS.get(slug, slug.replace("-", " ").title())
    )
    return slug, label


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    temp.replace(path)


def log_event(event_type: str, **kwargs: Any) -> None:
    record = {
        "timestamp": utc_now(),
        "event": event_type,
        **kwargs,
    }

    line = json.dumps(record, ensure_ascii=False, default=str)
    
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")

    print(line, flush=True)


def ensure_directories() -> None:
    for directory in (
        IMPORT_DIRECTORY,
        OUTPUT_DIRECTORY,
        WORK_DIRECTORY,
        PENDING_DIRECTORY,
        PROCESSED_DIRECTORY,
        FAILED_DIRECTORY,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def clean_text(value: Any, maximum: int = 1000) -> str:
    rendered = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    return rendered[:maximum]


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    rendered = str(value)
    rendered = rendered.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", rendered)

    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def integer(value: Any, default: int = 0) -> int:
    parsed = number(value)

    if parsed is None:
        return default

    return int(parsed)


def find_database_products() -> list[Product]:
    # Esta instalacao utiliza as importacoes JSON.
    return []

def discover_products() -> list[Product]:
    products: list[Product] = []

    # Importa JSONs (Scrapers / OMNI)
    if IMPORT_DIRECTORY.exists():
        for path in IMPORT_DIRECTORY.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        # Extrai URLs ignorando dicionários complexos se for o caso
                        img_url = item.get("image_url")
                        if isinstance(img_url, dict): img_url = img_url.get("url") or img_url.get("URL") or ""

                        slug, label = _category_of(item)
                        products.append(
                            Product(
                                marketplace_code=item.get("marketplace_code", "BR"),
                                asin=item.get("asin", ""),
                                title=item.get("title", ""),
                                price_display=item.get("price_display", ""),
                                image_url=img_url or "",
                                detail_url=item.get("affiliate_url", ""),
                                source=item.get("source", "import"),
                                category=slug,
                                category_label=label,
                                rating=number(item.get("rating")),
                                review_count=integer(item.get("review_count"), 0)
                                or None,
                            )
                        )
            except Exception as e:
                log_event("IMPORT_ERROR", file=path.name, error=str(e))

    # Busca do Banco de Dados
    db_products = find_database_products()
    products.extend(db_products)

    log_event(
        "PRODUCT_DISCOVERY_COMPLETED",
        total_found=len(products)
    )

    return products


def pending_product_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()

    # PENDING/PROCESSED = videos aguardando aprovacao ou ja publicados.
    # OUTPUT_DIRECTORY = qualquer video ja gerado em disco (sidecar .json).
    # Assim, se o produto ja virou video, ele nao vira video de novo.
    for directory in (PENDING_DIRECTORY, PROCESSED_DIRECTORY, OUTPUT_DIRECTORY):
        if not directory.exists():
            continue

        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                market = data.get("marketplace_code")
                asin = data.get("asin")

                if market and asin:
                    keys.add((market, asin))
            except Exception:
                pass

    return keys


def score_product(product: Product) -> None:
    score = 10.0
    if product.review_count:
        score += min(product.review_count / 1000.0, 10.0)
    if product.rating:
        score += (product.rating - 3.5) * 2.0
    if product.discount_percent:
        score += min(product.discount_percent / 5.0, 5.0)
    product.score = max(0.0, round(score, 1))


def select_products(products: list[Product], maximum: int) -> list[Product]:
    already_processed = pending_product_keys()

    eligible = [
        p for p in products
        if (p.marketplace_code, p.asin) not in already_processed
        and p.title
        and p.detail_url
    ]

    for p in eligible:
        score_product(p)

    eligible.sort(key=lambda p: p.score, reverse=True)
    return eligible[:maximum]


def available_products() -> list[dict[str, Any]]:
    """Lista os produtos ainda NAO transformados em video, agrupados por
    mercado + categoria, para o painel montar a selecao.

    As categorias saem na ORDEM DOS MAIS VENDIDOS: quem tem os produtos
    mais fortes na Amazon (melhor pontuacao de vendas + posicao em que a
    Amazon devolveu o produto) aparece primeiro. BR e US sao ordenados
    separadamente."""
    already_processed = pending_product_keys()

    groups: dict[tuple[str, str], dict[str, Any]] = {}

    # A ordem em que a Amazon devolve os produtos ja reflete os mais vendidos
    # (primeiro = mais vendido). Guardamos essa posicao para desempate.
    for position, product in enumerate(discover_products()):
        if not product.title or not product.detail_url:
            continue
        if (product.marketplace_code, product.asin) in already_processed:
            continue

        # Numero de avaliacoes = melhor sinal de "quanto vendeu" (quanto mais
        # gente avaliou, mais vendeu). Estrelas servem de desempate.
        reviews = int(product.review_count or 0)
        rating = float(product.rating or 0.0)

        slug = product.category or "outros"
        label = product.category_label or CATEGORY_LABELS.get(slug, slug)
        key = (product.marketplace_code, slug)

        group = groups.get(key)
        if group is None:
            group = {
                "marketplace_code": product.marketplace_code,
                "category": slug,
                "category_label": label,
                "count": 0,
                "products": [],
                # Forca de venda da categoria = produto mais vendido dela.
                "best_reviews": 0,
                "best_rating": 0.0,
                "best_position": position,
            }
            groups[key] = group

        group["count"] += 1
        group["best_reviews"] = max(group["best_reviews"], reviews)
        group["best_rating"] = max(group["best_rating"], rating)
        group["best_position"] = min(group["best_position"], position)
        group["products"].append(
            {
                "asin": product.asin,
                "title": product.title,
                "price_display": product.price_display,
                "image_url": product.image_url,
                "reviews": reviews,
                "rating": rating,
                "position": position,
            }
        )

    # Dentro de cada categoria, os mais vendidos (mais avaliacoes) primeiro.
    for group in groups.values():
        group["products"].sort(
            key=lambda p: (-p["reviews"], -p["rating"], p["position"]),
        )

    # Ordena as categorias por mercado e, dentro do mercado, pelos MAIS
    # VENDIDOS: mais avaliacoes primeiro; empate, melhor nota; depois quem a
    # Amazon colocou mais no topo; por ultimo, ordem alfabetica.
    ordered = sorted(
        groups.values(),
        key=lambda g: (
            g["marketplace_code"],
            -g["best_reviews"],
            -g["best_rating"],
            g["best_position"],
            g["category_label"],
        ),
    )

    # Remove campos internos usados so para ordenar.
    for group in ordered:
        group.pop("best_reviews", None)
        group.pop("best_rating", None)
        group.pop("best_position", None)
        for item in group["products"]:
            item.pop("reviews", None)
            item.pop("rating", None)
            item.pop("position", None)

    return ordered


def _resolve_ffprobe_path() -> str | None:
    """Localiza o ffprobe. Pode nao existir (imageio-ffmpeg nao empacota ffprobe)."""
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        directory = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        for name in ("ffprobe.exe", "ffprobe"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


def _probe_video_moviepy(path: Path) -> dict[str, Any]:
    """Mede o video usando moviepy quando o ffprobe nao esta disponivel."""
    import moviepy.editor as mp

    clip = mp.VideoFileClip(str(path))
    try:
        width, height = clip.size
        video_duration = float(clip.duration or 0)
        has_audio = clip.audio is not None
    finally:
        clip.close()

    if not width or not height or not has_audio:
        raise PipelineError("O video final nao possui video ou audio.")

    return {
        "width": int(width),
        "height": int(height),
        # O video e sempre criado por nos com libx264 + aac.
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_seconds": video_duration,
        "size_bytes": path.stat().st_size,
    }


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe = _resolve_ffprobe_path()

    if not ffprobe:
        return _probe_video_moviepy(path)

    try:
        result = run_command(
            [
                ffprobe,
                "-v", "error",
                "-show_streams",
                "-show_format",
                "-of", "json",
                str(path),
            ]
        )
    except (FileNotFoundError, OSError):
        return _probe_video_moviepy(path)

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video or not audio:
        raise PipelineError("O video final nao possui video ou audio.")

    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "duration_seconds": float(data.get("format", {}).get("duration", 0)),
        "size_bytes": path.stat().st_size,
    }


def _resolve_edge_tts_command() -> list[str] | None:
    """Localiza o edge-tts de forma robusta.

    1. CLI no PATH (shutil.which).
    2. Executavel ao lado do Python atual (Scripts/edge-tts[.exe]).
    3. Fallback: python -m edge_tts (sempre funciona se o pacote estiver instalado).
    """
    cli = shutil.which("edge-tts")
    if cli:
        return [cli]

    scripts_dir = Path(sys.executable).parent
    for name in ("edge-tts.exe", "edge-tts"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return [str(candidate)]

    try:
        import edge_tts  # noqa: F401
        return [sys.executable, "-m", "edge_tts"]
    except Exception:
        return None


def create_voice(
    product: Product,
    text: str,
    destination: Path,
) -> bool:
    import html

    edge_tts_command = _resolve_edge_tts_command()

    if not edge_tts_command:
        log_event(
            "VOICE_GENERATION_FAILED",
            asin=product.asin,
            market=product.marketplace_code,
            error="edge-tts nao foi encontrado.",
        )
        return False

    cleaned_text = html.unescape(
        str(text or "")
    )

    cleaned_text = cleaned_text.replace(
        "\\u200b",
        " ",
    )

    cleaned_text = cleaned_text.replace(
        "\u200b",
        " ",
    )

    cleaned_text = re.sub(
        r"<[^>]+>",
        " ",
        cleaned_text,
    )

    cleaned_text = re.sub(
        r"\s+",
        " ",
        cleaned_text,
    ).strip()

    if len(cleaned_text) < 80:
        log_event(
            "VOICE_GENERATION_FAILED",
            asin=product.asin,
            market=product.marketplace_code,
            error="O roteiro ficou curto ou vazio.",
        )
        return False

    text_path = destination.with_suffix(
        ".txt"
    )

    text_path.write_text(
        cleaned_text,
        encoding="utf-8",
    )

    if product.marketplace_code == "BR":
        voices = [
            MARKETS[
                product.marketplace_code
            ]["voice"],
            "pt-BR-FranciscaNeural",
            "pt-BR-AntonioNeural",
            "pt-BR-ThalitaNeural",
        ]
    else:
        voices = [
            MARKETS[
                product.marketplace_code
            ]["voice"],
            "en-US-JennyNeural",
            "en-US-GuyNeural",
            "en-US-AriaNeural",
        ]

    unique_voices: list[str] = []

    for voice in voices:
        if voice and voice not in unique_voices:
            unique_voices.append(voice)

    errors: list[str] = []

    for voice in unique_voices:
        destination.unlink(
            missing_ok=True
        )

        command = [
            *edge_tts_command,
            "--voice",
            voice,
            "--rate=+5%",
            "--pitch=-2Hz",
            "--file",
            str(text_path),
            "--write-media",
            str(destination),
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=240,
            )

        except Exception as error:
            errors.append(
                voice
                + ": "
                + str(error)
            )
            continue

        if (
            completed.returncode == 0
            and destination.is_file()
            and destination.stat().st_size > 1000
        ):
            log_event(
                "VOICE_GENERATED",
                asin=product.asin,
                market=product.marketplace_code,
                voice=voice,
                size_bytes=destination.stat().st_size,
            )

            return True

        details = (
            completed.stderr
            or completed.stdout
            or "Sem detalhes."
        )

        errors.append(
            voice
            + ": codigo="
            + str(completed.returncode)
            + " "
            + details[-1200:]
        )

    log_event(
        "VOICE_GENERATION_FAILED",
        asin=product.asin,
        market=product.marketplace_code,
        error=" | ".join(errors)[-5000:],
    )

    return False

def create_video_for_product(product: Product) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    work = WORK_DIRECTORY / job_id
    work.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", product.title).strip("-")[:50]
    output_name = f"{product.marketplace_code.lower()}-{product.asin.lower()}-{slug}-{job_id[:8]}"
    
    video_path = OUTPUT_DIRECTORY / (output_name + ".mp4")
    approval_path = PENDING_DIRECTORY / (output_name + ".json")

    try:
        # Usa as funcoes do authorized_broll_renderer
        story = make_story(product)
        narration = narration_from_story(story)

        audio_path = work / "voice.mp3"
        voice_generated = create_voice(product, narration, audio_path)

        if not voice_generated:
            raise PipelineError("A voz IA nao foi gerada. O video nao sera criado sem narracao.")

        broll_metadata = render_authorized_video(
            product=product,
            audio_path=audio_path,
            output_path=video_path,
            work_directory=work,
        )

        probe = probe_video(video_path)

        approval_record = {
            "job_id": job_id,
            "status": "AWAITING_APPROVAL",
            "created_at": utc_now(),
            "publication_executed": False,
            "marketplace_code": product.marketplace_code,
            "marketplace": MARKETS[product.marketplace_code]["marketplace"],
            "partner_tag": MARKETS[product.marketplace_code]["partner_tag"],
            "asin": product.asin,
            "title": product.title,
            "affiliate_url": product.detail_url,
            "source": product.source,
            "opportunity_score": product.score,
            "video_path": str(video_path),
            "voice_generated": voice_generated,
            "script": story,
            "narration": narration,
            "broll": broll_metadata.get("broll", {}),
            "probe": probe,
            "product": asdict(product),
        }

        write_json(approval_path, approval_record)
        log_event("VIDEO_AWAITING_APPROVAL", job_id=job_id, asin=product.asin, video=video_path.name)

        # Sidecar ao lado do .mp4 para o painel indexar o video de afiliado
        # e gerar o LINK CLICAVEL (link curto) que vai na legenda/descricao.
        try:
            sidecar_path = video_path.with_suffix(".json")
            write_json(
                sidecar_path,
                {
                    "kind": "affiliate",
                    "asin": product.asin,
                    "title": product.title,
                    "marketplace_code": product.marketplace_code,
                    "affiliate_url": product.detail_url,
                    "language": MARKETS[product.marketplace_code]["language"],
                    "job_id": job_id,
                    "created_at": utc_now(),
                    # Guardamos a NARRACAO e a CATEGORIA para que a analise
                    # automatica consiga conferir se o assunto do video bate
                    # com o produto antes de publicar sozinho.
                    "narration": narration,
                    "category": product.category,
                    "category_label": product.category_label,
                },
            )
        except Exception as sidecar_error:  # noqa: BLE001
            log_event(
                "SIDECAR_WRITE_FAILED",
                job_id=job_id,
                asin=product.asin,
                error=str(sidecar_error),
            )

        return approval_record

    except Exception as error:
        failure_path = FAILED_DIRECTORY / (output_name + ".json")
        write_json(failure_path, {
            "job_id": job_id,
            "status": "FAILED",
            "error": str(error),
            "product": asdict(product),
        })
        log_event("VIDEO_GENERATION_FAILED", job_id=job_id, asin=product.asin, error=str(error))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_pipeline(
    maximum_videos: int = 10,
    selection: list[dict[str, Any]] | None = None,
    progress_callback: Any = None,
    on_video_ready: Any = None,
) -> dict[str, Any]:
    ensure_directories()
    started_at = utc_now()
    target = max(1, maximum_videos)

    def _report(percent: float, title: str = "", stage: str = "") -> None:
        """Envia a % de progresso para o painel (igual aos reels)."""
        if not progress_callback:
            return
        try:
            safe = int(max(0, min(100, percent)))
            progress_callback(safe, title or "", stage or "")
        except Exception:
            pass

    log_event(
        "PIPELINE_STARTED",
        maximum_videos=target,
        strategy="SEARCH_UNTIL_SUCCESS",
        minimum_duration_seconds=30,
        maximum_duration_seconds=60,
        static_image_fallback=False,
    )

    products = discover_products()

    if not products:
        state = {
            "status": "WAITING_FOR_REAL_PRODUCT_SOURCE",
            "products_found": 0,
            "products_attempted": 0,
            "videos_created": 0,
            "target_videos": target,
        }
        write_json(STATE_PATH, state)
        return state

    already_processed = pending_product_keys()
    unique: dict[tuple[str, str], Product] = {}

    for product in products:
        key = (
            product.marketplace_code,
            product.asin,
        )
        if key not in unique:
            unique[key] = product

    eligible = [
        product
        for product in unique.values()
        if (
            product.marketplace_code,
            product.asin,
        ) not in already_processed
        and product.title
        and product.detail_url
    ]

    for product in eligible:
        score_product(product)

    priority_terms = (
        "fire tv",
        "echo",
        "alexa",
        "amazon",
        "samsung",
        "galaxy",
        "jbl",
        "logitech",
        "motorola",
        "xiaomi",
        "sony",
        "apple",
        "dell",
        "intelbras",
        "philco",
        "mondial",
        "oster",
    )

    eligible.sort(
        key=lambda product: (
            any(
                term in product.title.lower()
                for term in priority_terms
            ),
            product.score,
            product.review_count or 0,
        ),
        reverse=True,
    )

    # Se veio uma selecao do painel (categorias + quantidade por categoria),
    # filtra os produtos elegiveis para gerar apenas o que foi escolhido.
    if selection:
        wanted: dict[tuple[str, str], int] = {}
        for item in selection:
            try:
                market = str(item.get("marketplace_code") or "").strip().upper()
                category = str(item.get("category") or "").strip().lower()
                quantity = int(item.get("quantity") or 0)
            except Exception:
                continue
            if market and category and quantity > 0:
                wanted[(market, category)] = wanted.get((market, category), 0) + quantity

        picked: list[Product] = []
        used: dict[tuple[str, str], int] = {}
        for product in eligible:
            key = (product.marketplace_code, product.category or "outros")
            cap = wanted.get(key)
            if not cap or used.get(key, 0) >= cap:
                continue
            used[key] = used.get(key, 0) + 1
            picked.append(product)

        eligible = picked
        target = len(eligible)

    completed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    attempted = 0

    _report(0, "", "Preparando produtos…")

    for product in eligible:
        if len(completed) >= target:
            break

        attempted += 1

        _report(
            int(len(completed) / max(1, target) * 100),
            product.title,
            f"Gerando vídeo {len(completed) + 1} de {target}",
        )

        try:
            completed.append(
                create_video_for_product(product)
            )
            # Assim que ESTE video fica pronto, avisa quem pediu (o
            # job_service) para JA publicar este video — desde que passe
            # no controle de qualidade. Nao espera o lote inteiro terminar.
            if on_video_ready:
                try:
                    on_video_ready(completed[-1])
                except Exception:
                    pass
        except Exception as error:
            failures.append(
                {
                    "marketplace_code": product.marketplace_code,
                    "asin": product.asin,
                    "title": product.title,
                    "error": str(error),
                }
            )

            log_event(
                "PRODUCT_SKIPPED",
                market=product.marketplace_code,
                asin=product.asin,
                title=product.title,
                reason=str(error),
            )

    _report(100, "", "Vídeos gerados")

    if completed:
        status = "AWAITING_APPROVAL"
    elif eligible:
        status = "FAILED_NO_VALID_AUTHORIZED_BROLL"
    else:
        status = "NO_NEW_PRODUCTS"

    state = {
        "status": status,
        "started_at": started_at,
        "completed_at": utc_now(),
        "products_found": len(products),
        "products_unique": len(unique),
        "products_eligible": len(eligible),
        "products_attempted": attempted,
        "target_videos": target,
        "videos_created": len(completed),
        "failed_attempts": len(failures),
        "failures": failures,
        "publication_executed": False,
        "static_image_fallback": False,
        "pending_approval": [
            {
                "marketplace_code": record["marketplace_code"],
                "asin": record["asin"],
                "title": record["title"],
                "video_path": record["video_path"],
                "affiliate_url": record["affiliate_url"],
                "broll": record.get("broll", {}),
            }
            for record in completed
        ],
    }

    write_json(STATE_PATH, state)

    log_event(
        "PIPELINE_COMPLETED",
        status=status,
        products_attempted=attempted,
        target_videos=target,
        videos_created=len(completed),
        failed_attempts=len(failures),
        static_image_fallback=False,
    )

    return state

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-videos", type=int, default=10)
    arguments = parser.parse_args()

    # O Limite não tem mais trava rígida, ele aceita o que você mandar.
    result = run_pipeline(maximum_videos=arguments.max_videos)

    print("=" * 72)
    print("ATLAS AMAZON REAL PRODUCT PIPELINE - OMNI B-ROLL")
    print("=" * 72)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print("FINAL_STATUS=" + result["status"])


if __name__ == "__main__":
    main()