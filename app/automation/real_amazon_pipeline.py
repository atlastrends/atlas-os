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
    duration as audio_duration,
    make_story,
    narration_from_story,
    render_authorized_video,
    render_listing_video,
    render_live_variant,
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

# --- Fish Audio TTS (voz natural, multilingue) --------------------------------
# Provider primario opcional. Com FISH_API_KEY definido, a narracao usa o Fish
# (modelo gratuito "s2.1-pro-free"), que pronuncia palavras em ingles dentro do
# texto em portugues corretamente. Qualquer falha cai automaticamente no Edge.
FISH_API_BASE = os.getenv("FISH_API_BASE", "https://api.fish.audio").rstrip("/")
FISH_MODEL = os.getenv("FISH_MODEL", "s2.1-pro-free")
FISH_STATE_PATH = STORAGE / "fish_voice_state.json"

FISH_LANGUAGE_BY_MARKET: dict[str, tuple[str, ...]] = {
    "BR": ("pt-BR", "pt", "portuguese"),
    "US": ("en-US", "en", "english"),
}

# reference_ids fixos por mercado (opcional). Vazio = descoberta automatica.
FISH_VOICE_OVERRIDES: dict[str, dict[str, str]] = {
    "BR": {
        "female": os.getenv("FISH_VOICE_BR_FEMALE", "").strip(),
        "male": os.getenv("FISH_VOICE_BR_MALE", "").strip(),
    },
    "US": {
        "female": os.getenv("FISH_VOICE_US_FEMALE", "").strip(),
        "male": os.getenv("FISH_VOICE_US_MALE", "").strip(),
    },
}

# alternate (padrao) | random | female | male
FISH_VOICE_MODE = os.getenv("AFFILIATE_TTS_VOICE_MODE", "alternate").strip().lower()

_FISH_VOICE_CACHE: dict[str, dict[str, str]] = {}

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
    "automotive": "Automotivo",
    "fashion": "Moda",
    "books": "Livros",
    "grocery": "Mercado",
    "musical-instruments": "Instrumentos Musicais",
    "appliances": "Eletrodomesticos",
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
                # A Amazon nao expoe "unidades vendidas por dia/semana" nas
                # paginas publicas de Mais Vendidos. Usamos avaliacoes (review
                # count) e nota como o melhor sinal PUBLICO de popularidade
                # real, mais a posicao (rank) que a propria Amazon atribuiu.
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
        # Rank exibido no painel (1 = mais vendido da categoria) + rotulos
        # prontos para a UI, ja que review_count "puro" nao diz muito sozinho.
        for idx, item in enumerate(group["products"], start=1):
            item["rank"] = idx

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

    # Remove so os campos internos usados exclusivamente para ordenar as
    # CATEGORIAS (posicao/força agregada). Os campos por PRODUTO (reviews,
    # rating, rank) ficam no retorno: a UI usa isso para mostrar o
    # "indicador de popularidade" de cada produto ao expandir a categoria.
    for group in ordered:
        group.pop("best_reviews", None)
        group.pop("best_rating", None)
        group.pop("best_position", None)
        for item in group["products"]:
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


def _fish_enabled() -> bool:
    return bool(os.getenv("FISH_API_KEY", "").strip())


def _fish_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    key = os.getenv("FISH_API_KEY", "").strip()
    headers = {"Authorization": "Bearer " + key}
    if extra:
        headers.update(extra)
    return headers


def _fish_classify_gender(title: str, tags: Iterable[str]) -> str:
    blob = (title or "").lower() + " " + " ".join(
        str(tag).lower() for tag in (tags or [])
    )
    if re.search(
        r"\b(female|woman|women|feminina|feminino|feminine|girl|mulher)\b",
        blob,
    ):
        return "female"
    if re.search(
        r"\b(male|man|men|masculina|masculino|masculine|boy|homem)\b",
        blob,
    ):
        return "male"
    return "unknown"


# Tags de vozes que NAO servem para narracao (personagem/anime/jogo/filme).
_FISH_BAD_STYLE_TAGS = (
    "character-voice", "character", "cartoon", "anime", "gaming", "game",
    "videogame", "video-game", "movie", "film", "celebrity", "meme",
    "robot", "monster",
)

# Estilos de PESSOA NORMAL (conversa do dia a dia) - preferidos.
_FISH_CASUAL_STYLE_TAGS = (
    "conversational", "social-media", "casual", "natural", "friendly",
    "warm", "relaxed", "everyday", "chatty", "vlog", "gentle", "soft",
)

# Estilos de narracao suave (aceitaveis) - 2a opcao.
_FISH_SOFT_STYLE_TAGS = (
    "narration", "podcast", "storytelling", "calm", "sincere", "neutral",
    "audiobook", "educational",
)

# Estilos de LOCUTOR/propaganda que o usuario NAO quer (voz "de comercial").
_FISH_AVOID_STYLE_TAGS = (
    "announcer", "advertisement", "commercial", "cinematic", "authoritative",
    "dramatic", "epic", "trailer", "promo", "sports commentary",
    "sports-commentary", "hype",
)

# Nomes de franquias/personagens conhecidos (defesa extra por nome).
_FISH_BLOCKED_NAME_HINTS = (
    "mortal kombat", "smash bros", "super smash", "goku", "dragon ball",
    "naruto", "one piece", "pokemon", "pok\u00e9mon", "anime", "brainrot",
    "skibidi", "spongebob", "bob esponja", "capitao nascimento",
    "capit\u00e3o nascimento", "tropa de elite",
)


def _fish_style_ok(title: str, tags: Iterable[str]) -> bool:
    """True se a voz NAO parecer personagem/anime/filme/celebridade."""
    tag_blob = " ".join(str(tag).lower() for tag in (tags or []))
    if any(bad in tag_blob for bad in _FISH_BAD_STYLE_TAGS):
        return False
    name = (title or "").lower()
    return not any(hint in name for hint in _FISH_BLOCKED_NAME_HINTS)


def _fish_voice_rank(title: str, tags: Iterable[str]) -> int:
    """Prioridade de estilo (menor = melhor). 99 = personagem (descartar).

    0 = pessoa normal/conversa | 1 = narracao suave | 2 = neutra |
    3 = locutor/propaganda (so em ultimo caso).
    """
    if not _fish_style_ok(title, tags):
        return 99
    blob = " ".join(str(tag).lower() for tag in (tags or []))
    if any(avoid in blob for avoid in _FISH_AVOID_STYLE_TAGS):
        return 3
    if any(style in blob for style in _FISH_CASUAL_STYLE_TAGS):
        return 0
    if any(style in blob for style in _FISH_SOFT_STYLE_TAGS):
        return 1
    return 2


def _fish_discover_market_voices(market_code: str) -> dict[str, str]:
    """Descobre as melhores vozes (feminina/masculina) do Fish para o mercado.

    Ordem: overrides por env -> cache em processo -> API do Fish. Retorna
    {"female": reference_id, "male": reference_id}; ids podem ficar vazios se a
    API nao devolver vozes utilizaveis.
    """
    override = FISH_VOICE_OVERRIDES.get(market_code, {})
    picked = {
        "female": (override.get("female") or "").split(",")[0].strip(),
        "male": (override.get("male") or "").split(",")[0].strip(),
    }
    if picked["female"] and picked["male"]:
        return picked

    if market_code in _FISH_VOICE_CACHE:
        cached = _FISH_VOICE_CACHE[market_code]
        return {
            "female": picked["female"] or cached.get("female", ""),
            "male": picked["male"] or cached.get("male", ""),
        }

    languages = FISH_LANGUAGE_BY_MARKET.get(
        market_code, ("en-US", "en", "english")
    )
    items: list[dict[str, Any]] = []
    for lang in languages:
        try:
            response = requests.get(
                FISH_API_BASE + "/model",
                headers=_fish_headers(),
                params={
                    "language": lang,
                    "sort_by": "score",
                    "page_size": 30,
                },
                timeout=30,
            )
        except Exception:
            continue
        if response.status_code == 401:
            log_event(
                "FISH_AUTH_FAILED",
                market=market_code,
                error="Chave Fish invalida (401).",
            )
            return picked
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        items = payload.get("items") or []
        if items:
            break

    female_id = picked["female"]
    male_id = picked["male"]
    female_rank = 99
    male_rank = 99
    # Escolhe a MELHOR voz por genero: pessoa normal (0) > narracao suave (1) >
    # neutra (2) > locutor/propaganda (3). Personagem/anime/filme fica de fora.
    for entry in items:
        reference = str(entry.get("_id") or "").strip()
        if not reference:
            continue
        title = entry.get("title", "")
        tags = entry.get("tags", [])
        rank = _fish_voice_rank(title, tags)
        if rank >= 99:
            continue
        gender = _fish_classify_gender(title, tags)
        if gender == "female" and not picked["female"] and rank < female_rank:
            female_id, female_rank = reference, rank
        elif gender == "male" and not picked["male"] and rank < male_rank:
            male_id, male_rank = reference, rank

    # Ainda faltou (genero nao identificado): usa as melhores vozes distintas,
    # preferindo as "limpas" (sem personagem/anime/filme).
    if (not female_id or not male_id) and items:
        clean = [
            str(e.get("_id") or "").strip()
            for e in items
            if e.get("_id")
            and _fish_style_ok(e.get("title", ""), e.get("tags", []))
        ]
        pool = clean or [
            str(e.get("_id") or "").strip() for e in items if e.get("_id")
        ]
        pool = [t for t in pool if t]
        if not female_id and pool:
            female_id = pool[0]
        if not male_id:
            male_id = next((t for t in pool if t != female_id), female_id)

    result = {"female": female_id, "male": male_id}
    _FISH_VOICE_CACHE[market_code] = result
    return result


def _fish_bump_counter(key: str = "counter") -> int:
    """Contador PERSISTIDO por CHAVE (ex.: "BR:reel"). Cada fluxo (reel de
    afiliado, live, trend) alterna F/M de forma INDEPENDENTE. Antes era um unico
    contador global: como o afiliado gera 2 vozes por produto (reel+live), a
    paridade do reel nunca trocava e ele saia SEMPRE na mesma voz (feminina)."""
    try:
        data: dict[str, Any] = {}
        if FISH_STATE_PATH.is_file():
            loaded = json.loads(FISH_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        current = int(data.get(key, 0))
        data[key] = current + 1
        FISH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FISH_STATE_PATH.write_text(json.dumps(data), encoding="utf-8")
        return current
    except Exception:
        return 0


def _fish_next_voice(market_code: str, stream: str = "default") -> tuple[str, str]:
    """Escolhe (reference_id, rotulo) alternando feminino/masculino por video.

    `stream` separa os contadores (ex.: "reel", "live", "trend") para cada fluxo
    alternar por conta propria."""
    voices = _fish_discover_market_voices(market_code)
    female_id = voices.get("female", "")
    male_id = voices.get("male", "")

    if FISH_VOICE_MODE == "female" and female_id:
        return female_id, "fish-feminina"
    if FISH_VOICE_MODE == "male" and male_id:
        return male_id, "fish-masculina"

    available: list[tuple[str, str]] = []
    if female_id:
        available.append((female_id, "fish-feminina"))
    if male_id and male_id != female_id:
        available.append((male_id, "fish-masculina"))
    if not available:
        return "", ""

    if FISH_VOICE_MODE == "random":
        import random
        return random.choice(available)

    index = _fish_bump_counter(f"{market_code}:{stream}")
    return available[index % len(available)]


def _fish_synthesize(
    text: str, reference_id: str, destination: Path
) -> tuple[bool, str]:
    """Gera a narracao via Fish Audio. Retorna (ok, detalhe_do_erro)."""
    body: dict[str, Any] = {
        "text": text,
        "format": "mp3",
        "mp3_bitrate": 128,
        "chunk_length": 300,
        "normalize": True,
        "latency": "normal",
        "prosody": {"speed": 1.0},
    }
    if reference_id:
        body["reference_id"] = reference_id

    try:
        response = requests.post(
            FISH_API_BASE + "/v1/tts",
            headers=_fish_headers({"model": FISH_MODEL}),
            json=body,
            timeout=180,
        )
    except Exception as error:
        return False, "excecao: " + str(error)

    if response.status_code != 200:
        try:
            detail = response.text[-400:]
        except Exception:
            detail = ""
        return False, "http " + str(response.status_code) + " " + detail

    content = response.content or b""
    if len(content) < 1000:
        return False, "audio muito pequeno (" + str(len(content)) + " bytes)"

    destination.unlink(missing_ok=True)
    destination.write_bytes(content)
    return True, ""


def create_voice(
    product: Product,
    text: str,
    destination: Path,
    stream: str = "reel",
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

    # Provider primario: Fish Audio (voz natural, pronuncia ingles dentro do
    # portugues). Falhou por qualquer motivo -> cai no Edge TTS abaixo.
    if _fish_enabled():
        fish_min_seconds = max(3.0, (len(cleaned_text) / 16.0) * 0.6)
        reference_id, voice_label = _fish_next_voice(product.marketplace_code, stream)
        if reference_id or voice_label:
            fish_ok, fish_detail = _fish_synthesize(
                cleaned_text, reference_id, destination
            )
            if fish_ok:
                try:
                    fish_seconds = float(audio_duration(destination))
                except Exception:
                    fish_seconds = 0.0
                if fish_seconds <= 0.0 or fish_seconds >= fish_min_seconds:
                    log_event(
                        "VOICE_GENERATED",
                        asin=product.asin,
                        market=product.marketplace_code,
                        voice=voice_label,
                        provider="fish",
                        reference_id=reference_id,
                        size_bytes=destination.stat().st_size,
                        audio_seconds=round(fish_seconds, 1),
                    )
                    return True
                log_event(
                    "FISH_AUDIO_TRUNCATED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    audio_seconds=round(fish_seconds, 1),
                    min_seconds=round(fish_min_seconds, 1),
                )
            else:
                log_event(
                    "FISH_GENERATION_FAILED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    error=fish_detail[-800:],
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

    # edge-tts as vezes retorna sucesso (rc=0) mas com o audio TRUNCADO (so
    # parte da narracao) -> gerava reel curto, sem o pitch final. Exigimos que a
    # duracao do audio seja compativel com o texto; se vier truncado, tentamos
    # de novo e guardamos o maior audio como ultimo recurso.
    expected_seconds = len(cleaned_text) / 16.0  # ~16 caracteres por segundo
    min_seconds = max(3.0, expected_seconds * 0.6)

    best_backup = destination.with_name(destination.stem + ".best.mp3")
    best_seconds = 0.0

    for voice in unique_voices:
        for _attempt in range(2):
            destination.unlink(
                missing_ok=True
            )

            command = [
                *edge_tts_command,
                "--voice",
                voice,
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
                break

            if not (
                completed.returncode == 0
                and destination.is_file()
                and destination.stat().st_size > 1000
            ):
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
                    + details[-800:]
                )
                break

            try:
                seconds = float(audio_duration(destination))
            except Exception:
                seconds = 0.0

            # Sem medicao (0.0) ou audio completo -> aceita.
            if seconds <= 0.0 or seconds >= min_seconds:
                log_event(
                    "VOICE_GENERATED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    voice=voice,
                    size_bytes=destination.stat().st_size,
                    audio_seconds=round(seconds, 1),
                )
                best_backup.unlink(missing_ok=True)
                return True

            # Audio truncado: guarda o maior ate agora e tenta de novo.
            if seconds > best_seconds:
                best_seconds = seconds
                shutil.copyfile(destination, best_backup)

            errors.append(
                voice
                + ": audio truncado "
                + format(seconds, ".1f")
                + "s (minimo "
                + format(min_seconds, ".1f")
                + "s)"
            )

    # Nenhuma voz entregou a narracao completa: usa o maior audio obtido
    # (melhor um reel um pouco curto do que nenhum), se houver.
    if best_seconds > 0.0 and best_backup.is_file():
        shutil.copyfile(best_backup, destination)
        best_backup.unlink(missing_ok=True)
        log_event(
            "VOICE_GENERATED",
            asin=product.asin,
            market=product.marketplace_code,
            voice="melhor_truncado",
            size_bytes=destination.stat().st_size,
            audio_seconds=round(best_seconds, 1),
        )
        return True

    best_backup.unlink(missing_ok=True)

    log_event(
        "VOICE_GENERATION_FAILED",
        asin=product.asin,
        market=product.marketplace_code,
        error=" | ".join(errors)[-5000:],
    )

    return False

def create_video_for_product(product: Product, report: Any = None) -> dict[str, Any]:
    def _sub(fraction: float, stage: str) -> None:
        # Progresso DENTRO deste video (0..1). O run_pipeline converte para a
        # % global, fazendo a barra andar durante a criacao (nao so no fim).
        if not report:
            return
        try:
            report(fraction, stage)
        except Exception:
            pass

    job_id = str(uuid.uuid4())
    work = WORK_DIRECTORY / job_id
    work.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", product.title).strip("-")[:50]
    output_name = f"{product.marketplace_code.lower()}-{product.asin.lower()}-{slug}-{job_id[:8]}"
    
    video_path = OUTPUT_DIRECTORY / (output_name + ".mp4")
    approval_path = PENDING_DIRECTORY / (output_name + ".json")

    try:
        # Usa as funcoes do authorized_broll_renderer
        _sub(0.03, "gerando roteiro")
        story = make_story(product)
        narration = narration_from_story(story)

        _sub(0.12, "gerando narração (voz)")
        audio_path = work / "voice.mp3"
        voice_generated = create_voice(product, narration, audio_path)

        if not voice_generated:
            raise PipelineError("A voz IA nao foi gerada. O video nao sera criado sem narracao.")

        _sub(0.20, "baixando mídia do anúncio (fotos/vídeo)")
        broll_metadata = render_listing_video(
            product=product,
            audio_path=audio_path,
            output_path=video_path,
            work_directory=work,
            report=_sub,
        )

        _sub(0.88, "salvando vídeo")
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
                    # Marca e caracteristicas do anuncio p/ gerar hashtags
                    # fieis ao produto na hora de publicar.
                    "brand": product.brand,
                    "features": product.features,
                },
            )
        except Exception as sidecar_error:  # noqa: BLE001
            log_event(
                "SIDECAR_WRITE_FAILED",
                job_id=job_id,
                asin=product.asin,
                error=str(sidecar_error),
            )

        # ------------------------------------------------------------------
        # VERSAO DE LIVE (2o video): MESMA filmagem do reels, mas com uma
        # narracao de apresentadora AO VIVO (mais explicativa e apelativa) e
        # a legenda do que esta sendo falado. SEM ganchos de reels e SEM QR.
        # O audio original do reels NAO entra na live -- ele serve so pro reels.
        # Reaproveita o b-roll que o render do reels ja baixou (ainda esta na
        # pasta de trabalho, so limpa no finally). Se falhar, o reels segue ok.
        # ------------------------------------------------------------------
        try:
            broll_path = broll_metadata.get("broll_path")
            if broll_path and Path(broll_path).is_file():
                _sub(0.90, "gerando versão live")
                live_story = make_story(product, mode="live")
                live_narration = narration_from_story(live_story)
                live_audio = work / "voice_live.mp3"

                if create_voice(product, live_narration, live_audio, stream="live"):
                    live_video_path = OUTPUT_DIRECTORY / (output_name + ".live.mp4")
                    live_meta = render_live_variant(
                        product=product,
                        broll_path=Path(broll_path),
                        live_audio_path=live_audio,
                        live_narration=live_narration,
                        output_path=live_video_path,
                        work_directory=work,
                    )

                    # Sidecar da live: kind="affiliate_live" para a montagem
                    # preferir ESTE video (com audio de live) no lugar do reels.
                    write_json(
                        live_video_path.with_suffix(".json"),
                        {
                            "kind": "affiliate_live",
                            "asin": product.asin,
                            "title": product.title,
                            "marketplace_code": product.marketplace_code,
                            "affiliate_url": product.detail_url,
                            "language": MARKETS[product.marketplace_code]["language"],
                            "job_id": job_id,
                            "created_at": utc_now(),
                            "narration": live_narration,
                            "category": product.category,
                            "category_label": product.category_label,
                            "brand": product.brand,
                            "features": product.features,
                            "reel_video": video_path.name,
                            "duration_seconds": live_meta.get("duration_seconds"),
                        },
                    )
                    log_event(
                        "LIVE_VARIANT_READY",
                        job_id=job_id,
                        asin=product.asin,
                        video=live_video_path.name,
                    )
                else:
                    log_event(
                        "LIVE_VARIANT_SKIPPED",
                        job_id=job_id,
                        asin=product.asin,
                        error="voz da live nao foi gerada",
                    )
            else:
                log_event(
                    "LIVE_VARIANT_SKIPPED",
                    job_id=job_id,
                    asin=product.asin,
                    error="b-roll do reels indisponivel para reaproveitar",
                )
        except Exception as live_error:  # noqa: BLE001
            log_event(
                "LIVE_VARIANT_FAILED",
                job_id=job_id,
                asin=product.asin,
                error=str(live_error),
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

        done_before = len(completed)
        _report(
            int(done_before / max(1, target) * 100),
            product.title,
            f"Gerando vídeo {done_before + 1} de {target}",
        )

        def _sub_progress(
            fraction: float,
            stage: str,
            _title: str = product.title,
            _base: int = done_before,
        ) -> None:
            # Converte o progresso DENTRO do video (0..1) em % global, para a
            # barra andar durante a criacao — e nao ficar parada ate o fim.
            frac = max(0.0, min(1.0, float(fraction)))
            overall = (_base + frac) / max(1, target) * 100
            _report(overall, _title, f"Vídeo {_base + 1} de {target}: {stage}")

        try:
            completed.append(
                create_video_for_product(product, report=_sub_progress)
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