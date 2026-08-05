from __future__ import annotations

from pathlib import Path
from typing import Any
import html as _htmlmod
import json
import os
import re
import shutil
import subprocess
import sys
import time

import qrcode
import requests


MIN_DURATION = 30.0
MAX_DURATION = 60.0
TARGET_DURATION = 48.0


try:
    from google import genai as _genai
except Exception:
    _genai = None


_GEMINI_CLIENT: Any = None
_GEMINI_READY = False


def _gemini_client() -> Any:
    """Cliente Gemini (lazy, criado uma vez). Retorna None se indisponivel."""
    global _GEMINI_CLIENT, _GEMINI_READY
    if _GEMINI_READY:
        return _GEMINI_CLIENT
    _GEMINI_READY = True
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or _genai is None:
        _GEMINI_CLIENT = None
        return None
    try:
        _GEMINI_CLIENT = _genai.Client(api_key=key)
        print("[BROLL] Gemini pronto para roteiro de afiliado.")
    except Exception as exc:
        print(f"[BROLL] Gemini indisponivel para roteiro: {exc}")
        _GEMINI_CLIENT = None
    return _GEMINI_CLIENT


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


def _resolve_ffprobe() -> str | None:
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


_FFMPEG = _resolve_ffmpeg()
_FFPROBE = _resolve_ffprobe()


def _resolve_yt_dlp() -> str | None:
    """Localiza o yt-dlp (PATH ou Scripts do Python atual, como a venv)."""
    exe = shutil.which("yt-dlp")
    if exe:
        return exe
    scripts_dir = Path(sys.executable).parent
    for name in ("yt-dlp.exe", "yt-dlp"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return str(candidate)
    return None


_ATLAS_ROOT = Path(os.getenv("ATLAS_ROOT", os.getcwd()))


def _installed_cookie_browsers() -> list[str]:
    """Navegadores instalados cujos cookies o yt-dlp consegue ler (Windows)."""
    local = os.getenv("LOCALAPPDATA", "")
    appdata = os.getenv("APPDATA", "")
    checks = [
        ("edge", os.path.join(local, "Microsoft", "Edge", "User Data")),
        ("chrome", os.path.join(local, "Google", "Chrome", "User Data")),
        ("brave", os.path.join(
            local, "BraveSoftware", "Brave-Browser", "User Data")),
        ("firefox", os.path.join(appdata, "Mozilla", "Firefox", "Profiles")),
    ]
    found: list[str] = []
    for name, path in checks:
        try:
            if path and os.path.isdir(path):
                found.append(name)
        except Exception:
            continue
    return found


def _cookie_variants() -> list[list[str]]:
    """Lista ordenada de conjuntos de args do yt-dlp para autenticar.

    Evita o bloqueio 'confirme que nao e um robo'. Tenta, em ordem:
    1. YOUTUBE_COOKIES_BROWSER (navegador forcado, ex.: 'edge'/'chrome')
    2. YOUTUBE_COOKIES_FILE ou <ATLAS_ROOT>/storage/youtube_cookies.txt
    3. Navegadores instalados (edge/chrome/brave/firefox), um a um
    4. Sem cookies (comportamento antigo, ultimo recurso)
    Assim funciona em qualquer maquina/rede sem configuracao manual.
    """
    variants: list[list[str]] = []

    browser = (os.getenv("YOUTUBE_COOKIES_BROWSER") or "").strip()
    if browser:
        variants.append(["--cookies-from-browser", browser])

    file_candidates: list[Path] = []
    file_env = (os.getenv("YOUTUBE_COOKIES_FILE") or "").strip()
    if file_env:
        file_candidates.append(Path(file_env))
    file_candidates.append(_ATLAS_ROOT / "storage" / "youtube_cookies.txt")
    for candidate in file_candidates:
        try:
            if candidate.is_file():
                variants.append(["--cookies", str(candidate)])
        except Exception:
            continue

    if not browser:
        for name in _installed_cookie_browsers():
            variants.append(["--cookies-from-browser", name])

    variants.append([])  # ultimo recurso: sem cookies

    seen: set[tuple[str, ...]] = set()
    unique: list[list[str]] = []
    for variant in variants:
        key = tuple(variant)
        if key not in seen:
            seen.add(key)
            unique.append(variant)
    return unique


def _player_client_args() -> list[str]:
    """Args do yt-dlp que BURLAM o 'confirme que nao e um robo' SEM cookies.

    Usa clientes alternativos do YouTube (tv/ios/android/...) que nao exigem
    login. Funciona automaticamente em qualquer maquina/rede, sem configurar
    nada. Pode ser sobrescrito com a env ATLAS_YTDLP_PLAYER_CLIENTS (csv).
    Limitacao: esses clientes costumam liberar ate 360p (HD exige login).
    """
    raw = (os.getenv("ATLAS_YTDLP_PLAYER_CLIENTS") or "").strip()
    if raw:
        clients = [c.strip() for c in raw.split(",") if c.strip()]
    else:
        clients = ["tv", "ios", "android", "web_safari", "mweb"]
    if not clients:
        return []
    return ["--extractor-args", "youtube:player_client=" + ",".join(clients)]


class BrollError(RuntimeError):
    pass


def run(
    command: list[str],
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )

    if completed.returncode != 0:
        details = (
            completed.stderr
            or completed.stdout
            or "Sem detalhes."
        )

        raise BrollError(
            command[0]
            + " falhou, codigo "
            + str(completed.returncode)
            + ": "
            + details[-6000:]
        )

    return completed


def clean(
    value: Any,
    maximum: int = 300,
) -> str:
    import html

    text = html.unescape(
        str(value or "")
    )

    text = text.replace(
        "\\u200b",
        " ",
    )

    text = text.replace(
        "\u200b",
        " ",
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text[:maximum]

def short_title(product: Any) -> str:
    title = clean(
        getattr(product, "title", ""),
        130,
    )

    title = re.split(
        r"\s+[|–—]\s+",
        title,
    )[0]

    if len(title) > 90:
        title = title[:90].rsplit(" ", 1)[0]

    return title or "este produto"


def product_profile(product: Any) -> dict[str, str]:
    text = (
        clean(getattr(product, "title", ""), 300)
        + " "
        + clean(getattr(product, "description", ""), 300)
    ).lower()

    profiles = [
        (
            ("fire tv", "chromecast", "streaming", "roku"),
            {
                "pain": "sua televisão parece limitada, lenta ou sem os aplicativos que você usa",
                "benefit": "transformar uma TV compatível em uma central de entretenimento mais prática",
                "check": "resolução, aplicativos, conexão Wi-Fi e versão exata do dispositivo",
            },
        ),
        (
            ("echo", "alexa", "smart speaker", "caixa de som"),
            {
                "pain": "você interrompe suas tarefas para controlar músicas, alarmes e dispositivos",
                "benefit": "automatizar pequenas tarefas da rotina usando comandos de voz",
                "check": "geração, qualidade sonora e compatibilidade com outros dispositivos",
            },
        ),
        (
            ("smartphone", "celular", "iphone", "galaxy", "motorola"),
            {
                "pain": "seu celular trava, descarrega rápido ou não acompanha mais sua rotina",
                "benefit": "reunir desempenho, câmera e autonomia em um aparelho mais adequado ao dia a dia",
                "check": "memória, armazenamento, bateria, câmera e versão exata",
            },
        ),
        (
            ("fone", "headphone", "earbuds", "airpods", "buds"),
            {
                "pain": "ruído, fios ou chamadas ruins atrapalham seu trabalho, treino ou deslocamento",
                "benefit": "ouvir músicas e atender chamadas com mais liberdade",
                "check": "autonomia, encaixe, microfone, resistência e cancelamento de ruído",
            },
        ),
        (
            ("aspirador", "vassoura", "robo aspirador", "robô aspirador"),
            {
                "pain": "a limpeza consome mais tempo e esforço do que deveria",
                "benefit": "reduzir o esforço necessário para manter os ambientes limpos",
                "check": "potência, autonomia, acessórios, capacidade e superfícies indicadas",
            },
        ),
        (
            ("air fryer", "cafeteira", "liquidificador", "panela"),
            {
                "pain": "preparar alimentos está tomando tempo e gerando trabalho desnecessário",
                "benefit": "agilizar tarefas da cozinha com menos etapas",
                "check": "capacidade, potência, dimensões, funções e facilidade de limpeza",
            },
        ),
        (
            ("pilha", "bateria", "duracell", "elgin"),
            {
                "pain": "seus controles e acessórios ficam sem energia quando você mais precisa",
                "benefit": "manter dispositivos essenciais disponíveis com mais conveniência",
                "check": "tamanho, quantidade, validade e dispositivos compatíveis",
            },
        ),
        (
            ("mouse", "teclado", "monitor", "notebook", "gamer"),
            {
                "pain": "sua estação atual limita conforto, organização ou produtividade",
                "benefit": "deixar o uso diário mais confortável e eficiente",
                "check": "conectividade, dimensões, compatibilidade e recursos do modelo",
            },
        ),
    ]

    for keywords, profile in profiles:
        if any(keyword in text for keyword in keywords):
            return profile

    return {
        "pain": "você quer resolver isso logo e do jeito certo",
        "benefit": "ter exatamente o que você precisa, sem complicação",
        "check": "medidas, compatibilidade, materiais, recursos e condições atuais do anúncio",
    }


def english_product_profile(
    product: Any,
) -> dict[str, str]:
    text = (
        clean(
            getattr(product, "title", ""),
            350,
        )
        + " "
        + clean(
            getattr(product, "description", ""),
            350,
        )
    ).lower()

    profiles = [
        (
            (
                "fire tv",
                "roku",
                "chromecast",
                "streaming",
            ),
            {
                "pain": (
                    "your television still feels limited, slow, "
                    "or missing the apps you actually use"
                ),
                "benefit": (
                    "turn a compatible television into a more "
                    "convenient entertainment center"
                ),
                "check": (
                    "supported resolution, available apps, Wi-Fi "
                    "requirements, and the exact device generation"
                ),
            },
        ),
        (
            (
                "airpods",
                "earbuds",
                "headphone",
                "earpods",
            ),
            {
                "pain": (
                    "poor audio, uncomfortable earbuds, or unreliable "
                    "calls keep interrupting your routine"
                ),
                "benefit": (
                    "listen to music and handle calls with more freedom"
                ),
                "check": (
                    "battery life, fit, microphone quality, connection, "
                    "and compatibility with your devices"
                ),
            },
        ),
        (
            (
                "bottle",
                "tumbler",
                "water bottle",
                "travel mug",
            ),
            {
                "pain": (
                    "your current bottle leaks, is difficult to carry, "
                    "or does not keep drinks at the temperature you want"
                ),
                "benefit": (
                    "make daily hydration easier at work, in the car, "
                    "or during exercise"
                ),
                "check": (
                    "capacity, lid design, insulation, dimensions, "
                    "cleaning requirements, and cup-holder compatibility"
                ),
            },
        ),
        (
            (
                "scale",
                "thermometer",
                "toaster",
                "kitchen",
                "opener",
                "spinner",
            ),
            {
                "pain": (
                    "a simple kitchen task is taking more time or guesswork "
                    "than it should"
                ),
                "benefit": (
                    "make food preparation more consistent and convenient"
                ),
                "check": (
                    "capacity, dimensions, materials, controls, cleaning, "
                    "and the exact functions included"
                ),
            },
        ),
        (
            (
                "charger",
                "power strip",
                "surge protector",
                "usb",
            ),
            {
                "pain": (
                    "you never have enough accessible outlets or charging "
                    "ports where you need them"
                ),
                "benefit": (
                    "organize and power several compatible devices more easily"
                ),
                "check": (
                    "electrical rating, outlet spacing, USB output, cable "
                    "length, certification, and surge protection"
                ),
            },
        ),
        (
            (
                "car",
                "motor oil",
                "headlight",
                "windshield",
                "vehicle",
            ),
            {
                "pain": (
                    "a small vehicle problem keeps affecting visibility, "
                    "comfort, organization, or maintenance"
                ),
                "benefit": (
                    "handle a recurring automotive need more conveniently"
                ),
                "check": (
                    "vehicle compatibility, dimensions, materials, usage "
                    "instructions, and the exact product version"
                ),
            },
        ),
        (
            (
                "cat",
                "dog",
                "pet",
                "litter",
            ),
            {
                "pain": (
                    "daily pet care is creating unnecessary mess, odor, "
                    "or inconvenience"
                ),
                "benefit": (
                    "make one part of your pet-care routine easier to manage"
                ),
                "check": (
                    "size, quantity, ingredients, animal suitability, "
                    "directions, and safety information"
                ),
            },
        ),
    ]

    for keywords, profile in profiles:
        if any(
            keyword in text
            for keyword in keywords
        ):
            return profile

    return {
        "pain": (
            "you want to get this right without wasting "
            "money on the wrong option"
        ),
        "benefit": (
            "get exactly what you need without the hassle"
        ),
        "check": (
            "dimensions, compatibility, materials, included features, "
            "and the current listing details"
        ),
    }

def verified_feature(product: Any) -> str:
    for feature in list(
        getattr(product, "features", [])
        or []
    ):
        feature = clean(feature, 170)

        if len(feature) >= 20:
            return feature

    description = clean(
        getattr(product, "description", ""),
        170,
    )

    return description if len(description) >= 20 else ""


_ABOUT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Linhas que aparecem no bloco mas nao sao "Sobre este item" de verdade
# (vem de detalhes/avaliacoes). A gente descarta esse ruido; o usuario NAO
# quer detalhe minimo tipo peso/dimensao da embalagem.
_ABOUT_SKIP = re.compile(
    r"(date first available|best sellers rank|customer reviews"
    r"|item model number|\basin\b|numero do modelo"
    r"|avaliacoes de clientes|mais vendidos na"
    r"|\bpeso\b|\bpesa\b|\bweighs?\b|\bweight\b|\bdimens)",
    re.IGNORECASE,
)


def _about_dir() -> Path:
    base = os.getenv("ATLAS_ROOT") or ""
    root = (
        Path(base).resolve()
        if base
        else Path(__file__).resolve().parents[2]
    )
    return root / "storage" / "amazon"


def _about_cache_load() -> dict[str, Any]:
    try:
        path = _about_dir() / "about_cache.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _about_cache_save(cache: dict[str, Any]) -> None:
    try:
        folder = _about_dir()
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "about_cache.json.tmp"
        tmp.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(folder / "about_cache.json")
    except Exception:
        pass


def _parse_about_bullets(html: str) -> list[str]:
    """Extrai os itens de 'Sobre este item / About this item' (#feature-bullets)."""
    match = re.search(
        r'id="feature-bullets".*?</div>\s*</div>', html, re.DOTALL
    )
    block = match.group(0) if match else ""
    raw = re.findall(
        r'<span[^>]*class="[^"]*a-list-item[^"]*"[^>]*>(.*?)</span>',
        block,
        re.DOTALL,
    )
    bullets: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = re.sub(r"<[^>]+>", " ", item)
        text = _normalize_punct(re.sub(r"\s+", " ", text)).strip()
        if len(text) < 15 or _ABOUT_SKIP.search(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(text)
        if len(bullets) >= 6:
            break
    return bullets


def _about_this_item(detail_url: str) -> list[str]:
    """Le o 'Sobre este item' real da pagina do produto (com cache em disco)."""
    url = clean(detail_url, 400)
    asin_match = re.search(r"/dp/([A-Z0-9]{10})", url)
    if not asin_match:
        return []
    asin = asin_match.group(1)

    cache = _about_cache_load()
    cached = cache.get(asin)
    if cached:
        return [str(x) for x in cached]

    bullets: list[str] = []
    for attempt in range(2):
        try:
            res = requests.get(url, headers=_ABOUT_HEADERS, timeout=20)
            if res.status_code == 200:
                bullets = _parse_about_bullets(res.text)
                if bullets:
                    break
        except Exception:
            pass
        if attempt == 0:
            time.sleep(1.0)

    if bullets:
        cache[asin] = bullets
        _about_cache_save(cache)
    return bullets


def _enrich_about(product: Any) -> None:
    """Preenche product.features com o 'Sobre este item' real, se estiver vazio."""
    try:
        current = getattr(product, "features", None) or []
        existing = [f for f in current if str(f).strip()]
    except Exception:
        existing = []
    if existing:
        return
    detail = (
        clean(getattr(product, "detail_url", ""), 400)
        or clean(getattr(product, "affiliate_url", ""), 400)
    )
    if not detail:
        return
    try:
        bullets = _about_this_item(detail)
    except Exception:
        bullets = []
    if bullets:
        try:
            product.features = bullets
        except Exception:
            pass


def _product_facts(product: Any) -> str:
    """Junta os dados reais do produto (do anuncio Amazon) para o prompt da IA."""
    lines: list[str] = []

    title = clean(getattr(product, "title", ""), 300)
    if title:
        lines.append(f"Titulo: {title}")

    category = clean(
        getattr(product, "category_label", "")
        or getattr(product, "category", ""),
        120,
    )
    if category:
        lines.append(f"Categoria: {category}")

    price = clean(getattr(product, "price_display", ""), 60)
    if price and any(ch.isdigit() for ch in price):
        lines.append(f"Preco anunciado: {price}")

    rating = getattr(product, "rating", None)
    if rating:
        try:
            lines.append(f"Nota media: {float(rating):.1f} de 5")
        except Exception:
            pass

    features = getattr(product, "features", None) or []
    clean_features = []
    for feature in features:
        text = clean(feature, 200)
        if len(text) >= 8:
            clean_features.append(text)
    if clean_features:
        lines.append("Sobre este item (destaques reais do anuncio):")
        for item in clean_features[:6]:
            lines.append(f"- {item}")

    description = clean(getattr(product, "description", ""), 600)
    if description:
        lines.append(f"Descricao: {description}")

    return "\n".join(lines)


def _story_prompt(product: Any, market: str, mode: str = "reel") -> str:
    facts = _product_facts(product)

    if mode == "live":
        if market == "US":
            return (
                "You are a warm, professional LIVE shopping host presenting "
                "this Amazon product RIGHT NOW to viewers watching your "
                "livestream. Write her spoken lines in ENGLISH as 6 short "
                "blocks, for about 55 to 75 seconds, talking ONLY about THIS "
                "product, using its real details.\n\n"
                f"PRODUCT DATA (from the Amazon listing):\n{facts}\n\n"
                "RULES:\n"
                "- Real LIVE tone: warm, natural, talking WITH the customer in "
                "real time. Explain calmly and give MORE detail (it is live).\n"
                "- Be specific to THIS product: mention real features and uses.\n"
                "- Use the 'About this item' highlights as your base, but "
                "present it like a REAL salesperson: natural, in your own "
                "words, NOT like you are reading the listing. NEVER say "
                "'straight from the listing' or 'trademark' (or R/TM symbols) "
                "and NEVER mention weight, dimensions or packaging.\n"
                "- Build genuine DESIRE to buy: name the problem it solves, the "
                "practical benefit, why it is worth owning.\n"
                "- NO short-video hooks: do NOT say 'stop scrolling', 'three "
                "seconds', 'almost nobody knows'. This is a live, not a reel.\n"
                "- Do NOT invent specs not in the data. Do NOT mention "
                "discounts, sales, 'lowest price' or guarantees. Do NOT tell "
                "them to scan a QR code.\n"
                "- You may invite them to check the pinned link / link in the "
                "description (live language).\n"
                "- No emojis. Each block = 1 to 2 spoken sentences that flow "
                "naturally into the next.\n"
                "- Return ONLY valid JSON, no markdown, in this exact shape:\n"
                '{"scenes":[{"caption":"...","voice":"..."}, ... 6 items]}\n'
                "where 'voice' is the spoken line and 'caption' is a tiny "
                "3-5 word summary of that block (internal use)."
            )
        return (
            "Voce e uma APRESENTADORA de live de vendas, profissional e "
            "carismatica, apresentando AO VIVO este produto da Amazon para "
            "quem esta assistindo agora. Escreva a fala dela, em PORTUGUES DO "
            "BRASIL, em 6 blocos curtos, para cerca de 55 a 75 segundos, "
            "falando SO deste produto, com os dados reais dele.\n\n"
            f"DADOS DO PRODUTO (do anuncio da Amazon):\n{facts}\n\n"
            "REGRAS:\n"
            "- Tom de LIVE de verdade: acolhedor, natural, como quem conversa "
            "com o cliente em tempo real. Explique com calma e de MAIS "
            "detalhes (por ser ao vivo).\n"
            "- Seja especifica DESTE produto: cite caracteristicas e usos "
            "reais.\n"
            "- Use os itens de 'Sobre este item' como base, mas apresente como "
            "uma VENDEDORA de verdade: natural, no seu tom, SEM parecer que "
            "esta lendo o anuncio. NUNCA diga 'direto do anuncio' nem 'marca "
            "registrada' (nem simbolos R/TM) e NUNCA cite peso, dimensoes ou "
            "embalagem.\n"
            "- Desperte o DESEJO de compra: mostre o problema que ele resolve, "
            "o beneficio pratico, por que vale a pena ter.\n"
            "- NADA de gancho de reels: NAO diga 'pare de rolar o feed', 'tres "
            "segundos', 'quase ninguem sabe'. Isso e live, nao video curto.\n"
            "- NAO invente especificacoes que nao estao nos dados. NAO fale de "
            "desconto, promocao, 'menor preco' nem garantia. NAO mande "
            "escanear QR Code.\n"
            "- Pode convidar a conferir pelo link fixado / link na descricao "
            "(linguagem de live).\n"
            "- Sem emojis. Cada bloco = 1 a 2 frases faladas que se encadeiam "
            "naturalmente.\n"
            "- Retorne SOMENTE JSON valido, sem markdown, neste formato "
            "exato:\n"
            '{"scenes":[{"caption":"...","voice":"..."}, ... 6 itens]}\n'
            "onde 'voice' e a fala e 'caption' e um resumo curtinho de 3 a 5 "
            "palavras daquele bloco (uso interno)."
        )

    if market == "US":
        return (
            "You are a top-tier short-form video copywriter for an Amazon "
            "affiliate channel. Write a punchy, SPECIFIC 7-scene script in "
            "ENGLISH for a 45-55 second vertical video about the product "
            "below. The script MUST be about THIS exact product, using its "
            "real details.\n\n"
            f"PRODUCT DATA (from the Amazon listing):\n{facts}\n\n"
            "RULES:\n"
            "- Scenes 1 to 6 are ONLY about THIS product. Do NOT open with a "
            "generic line ('stop scrolling', 'almost nobody knows', 'you need "
            "to see this'). The FINAL scene (7) is the call to action.\n"
            "- Scene 1 (opening): start WITH the product - name it and the "
            "problem it solves or what it does. It is the hook, but it MUST be "
            "about this product.\n"
            "- Be specific to THIS product. Reference its real features/use.\n"
            "- Do NOT invent specs, data or uses that are not in the data "
            "above. Only say what the listing can back up.\n"
            "- Use the 'About this item' highlights as your base, but talk "
            "like a REAL salesperson recommending it: natural, in your own "
            "words, NOT like you are reading the listing. NEVER say 'straight "
            "from the listing' or 'trademark' (or R/TM symbols) and NEVER "
            "mention weight, dimensions or packaging.\n"
            "- Do NOT mention discounts, sales, 'lowest price' or guarantees.\n"
            "- Do NOT frame it as 'everyday', 'daily', a 'routine' or an "
            "'everyday problem', and do NOT assume how often they use it. "
            "Talk ONLY about THIS product's real features and value.\n"
            "- Natural creator tone, not corporate. No emojis in 'voice'.\n"
            "- Scene 5 must tell viewers to scan the QR code to see the full, "
            "updated listing for THIS product (mention the price can change).\n"
            "- Scene 6: close STILL on THIS product - restate the main benefit "
            "and why it is worth it.\n"
            "- Scene 7 (closing = CALL TO ACTION): tell viewers the link for "
            "THIS product is in the bio (tap the link) AND invite them to "
            "follow the page, because there are new products every day and "
            "they will not want to miss the next ones.\n"
            "- 'caption' = 3-6 word UPPERCASE on-screen hook for that scene.\n"
            "- 'voice' = 1-2 spoken sentences for that scene.\n"
            "- Return ONLY valid JSON, no markdown, in this exact shape:\n"
            '{"scenes":[{"caption":"...","voice":"..."}, ... 7 items]}'
        )

    return (
        "Voce e um copywriter TOP de video curto para um canal de afiliados "
        "da Amazon. Escreva um roteiro ESPECIFICO e chamativo, com 7 cenas, "
        "em PORTUGUES DO BRASIL, para um video vertical de 45 a 55 segundos "
        "sobre o produto abaixo. O roteiro TEM que ser sobre ESTE produto "
        "exato, usando os detalhes reais dele.\n\n"
        f"DADOS DO PRODUTO (do anuncio da Amazon):\n{facts}\n\n"
        "REGRAS:\n"
        "- As cenas 1 a 6 falam SO deste produto. NAO abra com frase generica "
        "('para de rolar o feed', 'quase ninguem sabe', 'voce precisa ver "
        "isso'). A cena FINAL (7) e a chamada pra acao.\n"
        "- Cena 1 (inicio): ja comece pelo PRODUTO - diga o nome dele e o "
        "problema que ele resolve ou o que ele faz de util. E o gancho, mas "
        "TEM que ser sobre ESTE produto.\n"
        "- Seja especifico DESTE produto. Cite caracteristicas/usos reais.\n"
        "- NAO invente especificacoes, dados ou usos que nao estao nos dados "
        "acima. Fale apenas o que da pra sustentar com o anuncio.\n"
        "- Use os itens de 'Sobre este item' como base, mas fale como um "
        "VENDEDOR de verdade recomendando: natural, no seu tom, SEM parecer "
        "que esta lendo o anuncio. NUNCA diga 'direto do anuncio' nem 'marca "
        "registrada' (nem simbolos R/TM) e NUNCA cite peso, dimensoes ou "
        "embalagem.\n"
        "- NAO fale de desconto, promocao, 'menor preco' nem garantia.\n"
        "- NAO enquadre como 'dia a dia', 'rotina' nem 'problema do dia a "
        "dia' e NAO suponha com que frequencia a pessoa usa. Fale SO das "
        "caracteristicas e do valor reais DESTE produto.\n"
        "- Tom de criador de conteudo, natural. Sem emojis no 'voice'.\n"
        "- A cena 5 deve pedir para escanear o QR Code e ver o anuncio "
        "completo e atualizado DESTE produto (diga que o preco pode mudar).\n"
        "- Cena 6: FECHE ainda falando DESTE produto - retome o principal "
        "beneficio e por que vale a pena.\n"
        "- Cena 7 (fim = CHAMADA PRA ACAO): diga que o link DESTE produto esta "
        "na bio (pra tocar no link) E convide pra seguir a pagina, porque tem "
        "produto novo todo dia e a pessoa nao vai querer perder os proximos.\n"
        "- 'caption' = gancho de 3 a 6 palavras em MAIUSCULAS para a cena.\n"
        "- 'voice' = 1 a 2 frases faladas para a cena.\n"
        "- Retorne SOMENTE JSON valido, sem markdown, neste formato exato:\n"
        '{"scenes":[{"caption":"...","voice":"..."}, ... 7 itens]}'
    )


def _normalize_punct(text: str) -> str:
    """Troca pontuacao "chique" por ASCII para nao atrapalhar a narracao/legenda."""
    replacements = {
        "\u2011": "-",   # hifen que nao quebra
        "\u2013": "-",   # travessao curto
        "\u2014": "-",   # travessao longo
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",   # espaco que nao quebra
        "\u2026": "...",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Remove marca registrada / trademark: a narracao falada leria "®" como
    # "marca registrada", e o usuario nao quer isso nos textos.
    text = text.replace("\u00ae", "").replace("\u2122", "").replace(
        "\u2120", ""
    )
    text = re.sub(
        r"\(?\s*\b(marcas? registradas?|registered trademarks?|trademarks?)"
        r"\b\s*\)?",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _parse_story_json(text: str) -> list[dict[str, str]]:
    cleaned = str(text or "").strip()
    cleaned = (
        cleaned.replace("```json", "")
        .replace("```JSON", "")
        .replace("```", "")
        .strip()
    )

    data: Any = None
    try:
        data = json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            data = json.loads(match.group(0))

    if isinstance(data, dict):
        scenes = data.get("scenes") or data.get("story") or []
    elif isinstance(data, list):
        scenes = data
    else:
        scenes = []

    result: list[dict[str, str]] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        caption = clean(_normalize_punct(str(scene.get("caption", ""))), 60)
        voice = clean(_normalize_punct(str(scene.get("voice", ""))), 600)
        if caption and voice:
            result.append({"caption": caption.upper(), "voice": voice})

    return result


def _gemini_story_text(prompt: str) -> str | None:
    """Tenta gerar o roteiro (JSON) com o Gemini. Retorna o texto cru ou None."""
    client = _gemini_client()
    if client is None:
        return None

    models: list[str] = []
    for name in (
        os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        os.getenv("GEMINI_MODEL_FALLBACK", "gemini-flash-latest"),
    ):
        name = (name or "").strip()
        if name and name not in models:
            models.append(name)

    for model in models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "temperature": 0.8,
                        "top_p": 0.9,
                        "max_output_tokens": 1200,
                        "response_mime_type": "application/json",
                    },
                )
            except Exception as exc:
                message = str(exc).lower()
                transient = (
                    "503" in message
                    or "unavailable" in message
                    or "overloaded" in message
                    or "high demand" in message
                )
                if transient and attempt < 1:
                    time.sleep(1.5)
                    continue
                break  # sem cota / modelo invalido -> proximo provedor
            text = getattr(response, "text", None)
            if text:
                return text
            break
    return None


_CONTENT_SERVICE: Any = None
_CONTENT_SERVICE_READY = False


def _content_service() -> Any:
    """ContentService (lazy) para acessar o Groq. None se indisponivel."""
    global _CONTENT_SERVICE, _CONTENT_SERVICE_READY
    if _CONTENT_SERVICE_READY:
        return _CONTENT_SERVICE
    _CONTENT_SERVICE_READY = True
    try:
        from app.services.content_service import ContentService
        _CONTENT_SERVICE = ContentService()
    except Exception as exc:
        print(f"[BROLL] Groq indisponivel para roteiro: {exc}")
        _CONTENT_SERVICE = None
    return _CONTENT_SERVICE


# Modelos do Groq em ordem de preferencia. Cada um tem cota diaria SEPARADA,
# entao quando um bate o limite (429) o proximo ainda funciona.
_GROQ_MODELS = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
)


def _groq_story_text(prompt: str) -> str | None:
    """Tenta gerar o roteiro (JSON) no Groq passando por varios modelos.

    Cada modelo do Groq tem cota diaria propria; se um bate o limite (429),
    tenta o proximo modelo, e assim por diante. Retorna o texto cru ou None.
    """
    service = _content_service()
    if service is None or getattr(service, "client", None) is None:
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "You output ONLY valid JSON, no markdown, no comments. "
                "You are an elite short-form affiliate video copywriter."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    for model in _GROQ_MODELS:
        request_kwargs: dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=0.8,
            max_tokens=1400,
            response_format={"type": "json_object"},
        )
        # Os modelos gpt-oss "pensam" antes de escrever; sem esforco baixo o
        # texto final pode voltar vazio.
        if "gpt-oss" in model:
            request_kwargs["reasoning_effort"] = "low"

        try:
            response = service.client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
                print(
                    f"[BROLL] Groq no limite ({model}); "
                    "tentando o proximo modelo."
                )
            else:
                print(f"[BROLL] Groq falhou ({model}): {exc}")
            continue

        try:
            text = response.choices[0].message.content
        except Exception:
            text = None
        if text and text.strip():
            return text

    return None


def _llm_story(product: Any, market: str, mode: str = "reel") -> list[dict[str, str]] | None:
    """Gera o roteiro com IA a partir dos dados reais do produto Amazon.

    Cadeia de fallback: tenta o Groq (varios modelos, cada um com cota
    diaria propria) e, se todos baterem o limite, cai no Gemini. So retorna
    None se tudo falhar (ai usa o template). Desligavel com
    AFFILIATE_LLM_SCRIPT=0.
    """
    if (os.getenv("AFFILIATE_LLM_SCRIPT") or "1").strip().lower() in {
        "0", "false", "no", "off"
    }:
        return None

    prompt = _story_prompt(product, market, mode)

    for provider, generator in (
        ("groq", _groq_story_text),
        ("gemini", _gemini_story_text),
    ):
        text = generator(prompt)
        if not text:
            continue
        try:
            scenes = _parse_story_json(text)
        except Exception:
            continue
        if len(scenes) >= 5:
            title = short_title(product)
            label = "de live" if mode == "live" else "de reels"
            print(
                f"[BROLL] Roteiro {label} gerado pela IA ({provider}): {title}"
            )
            return scenes[:7]

    print("[BROLL] IA sem cota/indisponivel, usando template especifico.")
    return None


# Palavras que, no fim de um rotulo, deixam o destaque incompleto ("Perfect
# for", "Ideal para") -> nesse caso preferimos a frase inteira.
_LABEL_TAIL_BAD = {
    "for", "para", "com", "de", "da", "do", "dos", "das", "e", "and",
    "with", "the", "a", "o", "to", "of", "por", "em", "que", "seu", "sua",
}


def _feature_line(feature: str) -> str:
    """Frase curta e natural a partir de um bullet cru do anuncio (fallback)."""
    text = _normalize_punct(clean(feature, 220)).strip()
    if not text:
        return ""
    # Bullets vem como "Rotulo do ponto: descricao...". Se o rotulo ja e um
    # destaque curto e completo, ele soa mais natural que a descricao longa.
    parts = text.split(":", 1)
    label = parts[0].strip() if len(parts) == 2 else ""
    words = label.split()
    if (
        2 <= len(words) <= 6
        and 8 <= len(label) <= 60
        and words[-1].lower() not in _LABEL_TAIL_BAD
    ):
        return label.rstrip(".;:, ")
    # Senao, usa a primeira frase (sem virar ficha tecnica lida em voz alta).
    text = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].strip()
    if len(text) > 150:
        text = text[:150].rsplit(" ", 1)[0]
    return text.rstrip(".;:, ")



def make_story(product: Any, mode: str = "reel") -> list[dict[str, str]]:
    _enrich_about(product)
    title = short_title(product)
    profile = product_profile(product)
    feature = verified_feature(product)
    feature_line = _feature_line(feature)

    market = clean(
        getattr(product, "marketplace_code", ""),
        10,
    ).upper()

    if market == "US":
        profile = english_product_profile(
            product
        )

    ai_story = _llm_story(product, market, mode)
    if ai_story:
        return ai_story

    if mode == "live":
        if market == "US":
            return [
                {"caption": "welcome", "voice": (
                    f"Hey everyone, welcome in! Let me show you the {title} - "
                    "I really think you are going to like this one.")},
                {"caption": "what it is", "voice": (
                    f"So what is it? It is made to help you {profile['benefit']}, "
                    "and it fits right into your everyday routine.")},
                {"caption": "real detail", "voice": (
                    f"One thing I really like about it: {feature_line}."
                    if feature_line else
                    "The full details are all on the listing - it is worth "
                    "taking a good look.")},
                {"caption": "why it is worth it", "voice": (
                    f"If {profile['pain']}, this is exactly the kind of thing "
                    "that solves it without any hassle. That is why it is worth "
                    "having at home.")},
                {"caption": "how to get it", "voice": (
                    "If you want it, the link is pinned right here and in the "
                    "description - go take a look at the full listing while "
                    "you are watching.")},
            ]
        return [
            {"caption": "boas-vindas", "voice": (
                f"Oi, gente, sejam bem-vindos! Deixa eu mostrar pra voces o "
                f"{title} - eu tenho certeza que voces vao gostar desse aqui.")},
            {"caption": "o que e", "voice": (
                f"Entao, o que e isso? Ele foi feito pra te ajudar a "
                f"{profile['benefit']}, e encaixa direitinho no seu dia a dia.")},
            {"caption": "detalhe real", "voice": (
                f"Um ponto que eu acho muito bacana nele: {feature_line}."
                if feature_line else
                "As informacoes e os detalhes completos estao no anuncio - "
                "vale conferir com calma.")},
            {"caption": "por que vale", "voice": (
                f"Se {profile['pain']}, esse aqui resolve exatamente isso, sem "
                "complicacao. Por isso vale muito a pena ter em casa.")},
            {"caption": "como pegar", "voice": (
                "Se voce quiser, o link ta fixado aqui e na descricao - da uma "
                "olhada no anuncio completo enquanto assiste.")},
        ]

    if market == "US":
        return [
            {
                "caption": "LOOK AT THIS PRODUCT",
                "voice": (
                    f"Let me show you the {title}. Take a good look at "
                    "this one."
                ),
            },
            {
                "caption": "WHAT STANDS OUT",
                "voice": (
                    f"What really stands out: {feature_line}."
                    if feature_line
                    else
                    f"This is the {title}. All the real details are right "
                    "there on the listing."
                ),
            },
            {
                "caption": "SEE THE LISTING BEFORE IT CHANGES",
                "voice": (
                    "Price and availability can change fast. "
                    "Scan the QR code and check the full, updated listing now."
                ),
            },
            {
                "caption": "LINK IN BIO",
                "voice": (
                    f"Like the {title}? The link is in my bio - just tap it to "
                    "see the full listing. And follow the page, because there "
                    "are new products every day so you never miss one."
                ),
            },
        ]

    return [
        {
            "caption": "OLHA ESSE PRODUTO",
            "voice": (
                f"Para tudo e olha esse {title}. Presta atenção nesse "
                "aqui."
            ),
        },
        {
            "caption": "O QUE CHAMA ATENÇÃO",
            "voice": (
                f"O que mais chama atenção nele: {feature_line}."
                if feature_line
                else
                f"Esse é o {title}. Todos os detalhes reais estão ali "
                "no anúncio."
            ),
        },
        {
            "caption": "OLHA O ANÚNCIO ANTES QUE MUDE",
            "voice": (
                "O preço e a disponibilidade podem mudar rápido. "
                "Escaneia o QR Code e confere o anúncio completo e atualizado."
            ),
        },
        {
            "caption": "O LINK TÁ NA BIO",
            "voice": (
                f"Gostou do {title}? O link tá na bio, é só tocar pra ver o "
                "anúncio completo. E segue a página, que todo dia tem produto "
                "novo pra você não perder nenhum."
            ),
        },
    ]


def narration_from_story(
    story: list[dict[str, str]],
) -> str:
    return " ".join(
        clean(scene.get("voice", ""), 600)
        for scene in story
    )


def approved_terms() -> list[str]:
    path = (
        Path("/atlas")
        / "storage"
        / "video_pipeline"
        / "approved_youtube_channels.json"
    )

    if not path.is_file():
        return []

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return []

    terms: list[str] = []

    for entry in data.get("channels", []):
        if isinstance(entry, str):
            value = clean(entry, 100).lower()
        elif isinstance(entry, dict):
            value = clean(
                entry.get("channel_name_contains", ""),
                100,
            ).lower()
        else:
            value = ""

        if value and value not in terms:
            terms.append(value)

    return terms


def search_query(product: Any) -> str:
    words = re.findall(
        r"[A-Za-zÀ-ÿ0-9]+",
        short_title(product),
    )

    ignored = {
        "com", "para", "mais", "modelo", "recente",
        "unidade", "unidades", "preto", "branco",
    }

    selected: list[str] = []

    for word in words:
        if len(word) < 3:
            continue

        if word.lower() in ignored:
            continue

        selected.append(word)

        if len(selected) >= 11:
            break

    return " ".join(selected)


def search_candidates(product: Any) -> list[dict[str, Any]]:
    executable = _resolve_yt_dlp()

    if not executable:
        raise BrollError("yt-dlp nao encontrado.")

    base = search_query(product)

    if not base:
        raise BrollError("Termos de busca do produto estao vazios.")

    # Busca ampla: o YouTube nao devolve nada para frases longas e muito
    # especificas (ex.: titulo inteiro da Amazon). Por isso usamos primeiro
    # buscas CURTAS (2-3 palavras), que sempre trazem resultado, e so depois
    # as versoes mais completas.
    words = base.split()
    w2 = " ".join(words[:2])
    w3 = " ".join(words[:3])
    w4 = " ".join(words[:4])
    queries = [
        w3 + " review",
        w2 + " review",
        w3,
        w2,
        w4 + " review",
        base + " review",
        base,
    ]
    # Remove duplicatas mantendo a ordem.
    seen_q: set[str] = set()
    queries = [q for q in queries if q and not (q in seen_q or seen_q.add(q))]

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    cookie_variants = _cookie_variants()
    player_args = _player_client_args()

    for query in queries:
        completed = None
        for cookies_args in cookie_variants:
            completed = subprocess.run(
                [
                    executable,
                    "--ignore-errors",
                    "--no-warnings",
                    *player_args,
                    *cookies_args,
                    "--skip-download",
                    "--dump-json",
                    "ytsearch15:" + query,
                ],
                check=False,
                text=True,
                capture_output=True,
                timeout=300,
            )
            stderr = (completed.stderr or "").lower()
            blocked = "sign in to confirm" in stderr or "not a bot" in stderr
            if completed.stdout.strip() and not blocked:
                break

        if completed is None:
            continue

        for line in completed.stdout.splitlines():
            try:
                candidate = json.loads(line)
            except Exception:
                continue

            video_id = clean(
                candidate.get("id"),
                100,
            )

            if video_id and video_id not in seen:
                seen.add(video_id)
                results.append(candidate)

    return results


def choose_candidates(product: Any) -> list[dict[str, Any]]:
    """Devolve os candidatos de b-roll ordenados do melhor para o pior."""
    allowed = approved_terms()

    raw_tokens = [
        token.lower()
        for token in re.findall(
            r"[A-Za-zÀ-ÿ0-9]+",
            search_query(product),
        )
        if len(token) >= 4
    ]

    def _stem(word: str) -> str:
        # Tira o plural simples (pantufas -> pantufa) para casar melhor.
        if len(word) > 4 and word.endswith("s"):
            return word[:-1]
        return word

    tokens = {_stem(token) for token in raw_tokens}

    # Palavra principal do produto (ex.: "pantufa"): vale um bonus forte,
    # para nao escolher um video de outro produto so porque uma palavra
    # secundaria (ex.: "felpudas") apareceu no titulo.
    primary = _stem(raw_tokens[0]) if raw_tokens else ""

    ranked: list[tuple[int, dict[str, Any]]] = []
    fallback: list[tuple[int, dict[str, Any]]] = []

    for candidate in search_candidates(product):
        title = clean(
            candidate.get("title"),
            300,
        ).lower()

        channel = clean(
            candidate.get("channel")
            or candidate.get("uploader")
            or candidate.get("channel_id"),
            180,
        ).lower()

        duration = float(
            candidate.get("duration")
            or 0
        )

        if duration < 15 or duration > 900:
            continue

        # Se ha lista de canais aprovados, filtra por ela.
        # Se a lista estiver vazia, aceita qualquer canal relevante.
        if allowed and not any(term in channel for term in allowed):
            continue

        overlap = sum(
            token in title
            for token in tokens
        )

        # Pontuacao base (duracao/orientacao/"official") serve tambem para
        # o plano B, quando nenhuma palavra bate exatamente.
        base_score = 0

        # Bonus forte se o titulo tem a palavra principal do produto.
        if primary and primary in title:
            base_score += 60

        if "official" in title:
            base_score += 10

        if duration >= 30:
            base_score += 8

        if int(candidate.get("height") or 0) > int(
            candidate.get("width") or 0
        ):
            base_score += 5

        # Guarda como plano B (ja passou pelo filtro de canal aprovado).
        fallback.append((base_score, candidate))

        if overlap < 1:
            continue

        ranked.append((overlap * 20 + base_score, candidate))

    if not ranked and not fallback:
        if allowed:
            raise BrollError(
                "Nenhum video relacionado foi encontrado nos canais aprovados."
            )
        raise BrollError(
            "Nenhum video relacionado foi encontrado no YouTube."
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    fallback.sort(key=lambda item: item[0], reverse=True)

    # Lista final: primeiro os candidatos com palavras batendo no titulo
    # (ranked), depois o resto relevante (fallback), sem repetir o mesmo
    # video. Isso da varias opcoes para pular candidatos com QR/codigo de
    # barras embutido (ver _video_has_qr_code) sem falhar a geracao.
    ordered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for _, candidate in ranked + fallback:
        video_id = clean(candidate.get("id"), 100)
        key = video_id or clean(candidate.get("webpage_url"), 200)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        ordered.append(candidate)

    return ordered


def choose_candidate(product: Any) -> dict[str, Any]:
    """Compatibilidade: devolve so o melhor candidato (ver choose_candidates)."""
    candidates = choose_candidates(product)
    return candidates[0]


def download_broll(
    candidate: dict[str, Any],
    work: Path,
) -> dict[str, Any]:
    executable = _resolve_yt_dlp()

    video_id = clean(
        candidate.get("id"),
        100,
    )

    url = clean(
        candidate.get("webpage_url"),
        1000,
    )

    if not url and video_id:
        url = "https://www.youtube.com/watch?v=" + video_id

    template = work / "youtube_broll.%(ext)s"

    base_command = [
        executable,
        "--no-playlist",
        "--no-warnings",
        "--merge-output-format",
        "mp4",
        "-f",
        "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/best/b",
        "-o",
        str(template),
        url,
    ]

    player_args = _player_client_args()
    if player_args:
        base_command[1:1] = player_args

    if _FFMPEG and _FFMPEG != "ffmpeg":
        base_command[1:1] = ["--ffmpeg-location", _FFMPEG]

    def _downloaded_files() -> list[Path]:
        return [
            path
            for path in work.glob("youtube_broll.*")
            if path.suffix.lower() in {
                ".mp4", ".webm", ".mkv", ".mov"
            }
            and path.stat().st_size > 150_000
        ]

    last_error: Exception | None = None
    files: list[Path] = []
    for cookies_args in _cookie_variants():
        for stale in work.glob("youtube_broll.*"):
            try:
                stale.unlink()
            except Exception:
                pass

        command = list(base_command)
        if cookies_args:
            command[1:1] = cookies_args

        try:
            run(command, timeout=1200)
        except Exception as exc:
            last_error = exc
            continue

        files = _downloaded_files()
        if files:
            break

    if not files:
        if last_error is not None:
            raise BrollError(
                "O download do b-roll falhou (YouTube pediu login/anti-robo "
                "em todos os navegadores). Detalhe: " + str(last_error)
            )
        raise BrollError(
            "O download nao gerou um arquivo de video valido."
        )

    files.sort(
        key=lambda path: path.stat().st_size,
        reverse=True,
    )

    return {
        "path": files[0],
        "source_url": url,
        "title": clean(candidate.get("title"), 300),
        "channel": clean(
            candidate.get("channel")
            or candidate.get("uploader"),
            180,
        ),
        "source_duration_seconds": float(
            candidate.get("duration")
            or 0
        ),
        "license_status": "user_approved_channel_list",
    }


def duration(path: Path) -> float:
    if _FFPROBE:
        completed = run(
            [
                _FFPROBE,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            timeout=180,
        )

        return float(completed.stdout.strip())

    # Sem ffprobe: mede a duracao lendo a saida do proprio ffmpeg.
    completed = subprocess.run(
        [_FFMPEG, "-i", str(path)],
        check=False,
        text=True,
        capture_output=True,
        timeout=180,
    )

    match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        completed.stderr or "",
    )

    if not match:
        raise BrollError(
            "Nao foi possivel medir a duracao do arquivo com o ffmpeg."
        )

    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _video_has_qr_code(path: Path, samples: int = 8) -> bool:
    """Verifica se o video de b-roll ja tem um QR code embutido na imagem.

    Usamos poucos frames amostrados (nao o video inteiro) para ser rapido.
    Se o OpenCV nao estiver instalado, retorna False (nao bloqueia a
    geracao; so deixa de aplicar essa checagem extra).
    """
    try:
        import cv2
    except Exception:
        print(
            "[BROLL] opencv nao instalado; pulando checagem de QR no b-roll."
        )
        return False

    capture = cv2.VideoCapture(str(path))
    try:
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames <= 0:
            return False

        detector = cv2.QRCodeDetector()
        step = max(total_frames // samples, 1)

        for index in range(samples):
            frame_index = min(index * step, total_frames - 1)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            try:
                found, _ = detector.detect(frame)
            except Exception:
                found = False
            if found:
                return True
    finally:
        capture.release()

    return False


def normalize_audio(
    source: Path,
    work: Path,
) -> tuple[Path, float]:
    # Mantem a narracao no ritmo NATURAL, sem acelerar nem desacelerar.
    # O tamanho do video passa a acompanhar a narracao; quem controla a
    # duracao e o tamanho do roteiro, e nao um esticamento/compressao do
    # audio (que era exatamente o que deixava a voz "acelerada").
    return source, duration(source)


def ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remainder = seconds % 60

    return (
        f"{hours}:{minutes:02d}:"
        f"{remainder:05.2f}"
    )


def ass_escape(value: str) -> str:
    return (
        clean(value, 180)
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def wrap_caption(value: str, max_chars: int, max_lines: int = 3) -> str:
    """Quebra a legenda em varias linhas curtas para nunca passar da largura.

    Retorna o texto ja ESCAPADO, com quebras de linha do ASS (\\N) entre as
    linhas. Assim uma frase como "STOP - AVOID THE WRONG PURCHASE" vira
    duas linhas legiveis em vez de uma linha cortada nas bordas.
    """
    words = clean(value, 180).split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = (current + " " + word).strip()
        if not current or len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    if len(lines) > max_lines:
        # junta o excedente na ultima linha permitida
        head = lines[: max_lines - 1]
        tail = " ".join(lines[max_lines - 1:])
        lines = head + [tail]

    return "\\N".join(ass_escape(line) for line in lines)


def create_ass(
    story: list[dict[str, str]],
    total_duration: float,
    destination: Path,
    market: str,
) -> None:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        (
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding"
        ),
        (
            "Style: Banner,DejaVu Sans,34,&H00FFFFFF,&H000000FF,"
            "&H00101010,&H99000000,-1,0,0,0,100,100,0,0,3,3,1,8,60,60,55,1"
        ),
        (
            "Style: Hook,DejaVu Sans,42,&H0000FFFF,&H000000FF,"
            "&H00101010,&HAA000000,-1,0,0,0,100,100,0,0,3,5,2,2,80,80,320,1"
        ),
        (
            "Style: Main,DejaVu Sans,40,&H00FFFFFF,&H000000FF,"
            "&H00101010,&HAA000000,-1,0,0,0,100,100,0,0,3,5,2,2,80,80,320,1"
        ),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]

    banner = (
        "ESCANEIE O QR CODE — CONFIRA O PRODUTO"
        if market == "BR"
        else
        "SCAN THE QR CODE — CHECK THE PRODUCT"
    )

    lines = header + [
        (
            "Dialogue: 0,0:00:00.00,"
            + ass_time(total_duration)
            + ",Banner,,0,0,0,,"
            + wrap_caption(banner, 26)
        )
    ]

    scene_duration = total_duration / len(story)

    for index, scene in enumerate(story):
        start = index * scene_duration
        end = min(
            total_duration,
            (index + 1) * scene_duration,
        )

        style = "Hook" if index in (0, len(story) - 1) else "Main"
        max_chars = 16 if style == "Hook" else 20

        lines.append(
            "Dialogue: 1,"
            + ass_time(start)
            + ","
            + ass_time(end)
            + ","
            + style
            + ",,0,0,0,,"
            + wrap_caption(scene["caption"], max_chars)
        )

    destination.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def create_live_ass(
    narration: str,
    total_duration: float,
    destination: Path,
    market: str,
) -> None:
    """Legenda estilo LIVE: mostra o que a apresentadora esta FALANDO,
    frase a frase, no rodape. Sem banner de QR e sem ganchos de reels."""
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        (
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding"
        ),
        (
            "Style: LiveCaption,DejaVu Sans,46,&H00FFFFFF,&H000000FF,"
            "&H00101010,&HB4000000,-1,0,0,0,100,100,0,0,3,4,2,2,90,90,210,1"
        ),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]

    # Quebra a narracao em frases para cada uma virar uma legenda curta.
    parts = re.split(r"(?<=[.!?])\s+", clean(narration, 4000))
    sentences = [p.strip() for p in parts if p and p.strip()]
    if not sentences:
        destination.write_text("\n".join(header), encoding="utf-8")
        return

    weights = [max(1, len(s)) for s in sentences]
    total_weight = sum(weights)
    lines = list(header)
    cursor = 0.0

    for sentence, weight in zip(sentences, weights):
        span = total_duration * (weight / total_weight)
        start = cursor
        end = min(total_duration, cursor + span)
        cursor = end
        lines.append(
            "Dialogue: 0,"
            + ass_time(start)
            + ","
            + ass_time(end)
            + ",LiveCaption,,0,0,0,,"
            + wrap_caption(sentence, 30, max_lines=3)
        )

    destination.write_text("\n".join(lines), encoding="utf-8")


def render_authorized_video(
    product: Any,
    audio_path: Path,
    output_path: Path,
    work_directory: Path,
    report: Any = None,
) -> dict[str, Any]:
    def _sub(fraction: float, stage: str) -> None:
        if not report:
            return
        try:
            report(fraction, stage)
        except Exception:
            pass

    if not audio_path.is_file():
        raise BrollError("A narracao nao foi criada.")

    audio, final_duration = normalize_audio(
        audio_path,
        work_directory,
    )

    # Tenta os candidatos do melhor para o pior, pulando qualquer video que
    # ja tenha um QR code embutido na imagem (atrapalharia o NOSSO QR do
    # produto, que fica sobreposto por cima do b-roll).
    _sub(0.25, "buscando vídeo de fundo")
    candidates = choose_candidates(product)

    broll: dict[str, Any] | None = None
    last_error: Exception | None = None
    max_attempts = min(len(candidates), 5)

    _sub(0.30, "baixando vídeo de fundo")
    for attempt_index in range(max_attempts):
        candidate = candidates[attempt_index]
        try:
            downloaded = download_broll(candidate, work_directory)
        except Exception as exc:
            last_error = exc
            continue

        if _video_has_qr_code(downloaded["path"]):
            print(
                "[BROLL] Candidato descartado (QR/codigo de barras "
                "embutido no video): " + downloaded.get("title", "")
            )
            try:
                downloaded["path"].unlink(missing_ok=True)
            except Exception:
                pass
            continue

        broll = downloaded
        break

    if broll is None:
        if last_error is not None:
            raise last_error
        raise BrollError(
            "Todos os videos encontrados ja tinham QR code ou codigo de "
            "barras na imagem; nenhum ficou livre para usar como fundo."
        )

    _sub(0.60, "montando legendas e QR")
    story = make_story(product)

    qr_path = work_directory / "product_qr.png"

    detail_url = clean(
        getattr(product, "detail_url", ""),
        1500,
    )

    if not detail_url.startswith(
        ("https://", "http://")
    ):
        raise BrollError("Link do produto invalido.")

    qrcode.make(detail_url).save(qr_path)

    ass_path = work_directory / "captions.ass"

    market = clean(
        getattr(product, "marketplace_code", ""),
        10,
    ).upper()

    create_ass(
        story,
        final_duration,
        ass_path,
        market,
    )

    _sub(0.65, "renderizando vídeo")

    filter_path = work_directory / "filters.txt"

    # O filtro "subtitles" do ffmpeg usa ':' e '\' como caracteres especiais.
    # Em Windows o caminho vira C:\... e quebra o filtro. Convertendo para
    # barras normais e escapando o ':' (ex.: C\:/Users/.../captions.ass).
    ass_for_filter = str(ass_path).replace("\\", "/").replace(":", "\\:")

    filter_path.write_text(
        (
            "[0:v]"
            "split=2"
            "[background_source]"
            "[foreground_source];"

            "[background_source]"
            "scale="
            "1080:1920:"
            "force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "gblur=sigma=42:steps=3,"
            "eq=brightness=-0.22:saturation=0.82,"
            "fps=30,"
            "setsar=1,"
            "format=yuv420p"
            "[background];"

            "[foreground_source]"
            "scale="
            "1080:1680:"
            "force_original_aspect_ratio=decrease,"
            "fps=30,"
            "setsar=1,"
            "format=yuv420p"
            "[foreground];"

            "[background]"
            "drawbox="
            "x=0:"
            "y=0:"
            "w=iw:"
            "h=ih:"
            "color=black@0.12:"
            "t=fill"
            "[dark_background];"

            "[dark_background]"
            "[foreground]"
            "overlay="
            "x=(W-w)/2:"
            "y=(H-h)/2:"
            "format=auto"
            "[composed];"

            "[1:v]"
            "scale=245:245,"
            "format=rgba"
            "[qr];"

            "[composed]"
            "[qr]"
            "overlay="
            "x=(W-w)/2:"
            "y=250:"
            "format=auto"
            "[withqr];"

            "[withqr]"
            "subtitles="
            "filename='"
            + ass_for_filter
            + "'"
            "[v]"
        ),
        encoding="utf-8",
    )

    run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(broll["path"]),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(qr_path),
            "-i",
            str(audio),
            "-filter_complex_script",
            str(filter_path),
            "-map",
            "[v]",
            "-map",
            "2:a:0",
            "-t",
            format(final_duration, ".3f"),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=1800,
    )

    if (
        not output_path.is_file()
        or output_path.stat().st_size < 300_000
    ):
        raise BrollError(
            "O FFmpeg nao criou um MP4 valido."
        )

    video_duration = duration(output_path)

    if video_duration < 30 or video_duration > 60:
        output_path.unlink(missing_ok=True)

        raise BrollError(
            "Video final fora de 30 a 60 segundos."
        )

    _sub(0.85, "vídeo renderizado")

    return {
        "broll": {
            "source_url": broll["source_url"],
            "title": broll["title"],
            "channel": broll["channel"],
            "source_duration_seconds": broll["source_duration_seconds"],
            "license_status": broll["license_status"],
        },
        "broll_path": str(broll["path"]),
        "story": story,
        "narration": narration_from_story(story),
        "duration_seconds": video_duration,
        "static_image_fallback": False,
        "original_audio_used": False,
    }


# ---------------------------------------------------------------------------
# MIDIA REAL DO ANUNCIO (fotos + video da propria Amazon)
# ---------------------------------------------------------------------------
# Em vez de buscar um b-roll no YouTube (que mostrava uma pessoa falando e nao
# o produto), o video de afiliado passa a usar a MIDIA DO PROPRIO ANUNCIO:
#   1) baixa as fotos do anuncio;
#   2) se o anuncio tiver video, usa SO o video;
#   3) se nao tiver video, mostra as fotos em loop (slideshow).
# A narracao (voz) continua sendo gerada exatamente como hoje.

_LISTING_IMAGE_HOSTS = (
    "m.media-amazon.com",
    "images-na.ssl-images-amazon.com",
    "images.amazon.com",
    "images-eu.ssl-images-amazon.com",
)


def _listing_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    }


def _listing_image_host_ok(url: str) -> bool:
    lowered = url.lower()
    return any(host in lowered for host in _LISTING_IMAGE_HOSTS)


def _clean_image_url(url: str) -> str:
    # Desescapa as barras que a Amazon poe no JSON do HTML
    # (https:\/\/m.media-amazon.com\/...) e remove o sufixo de tamanho
    # (._AC_SL1500_.jpg -> .jpg) para pegar a imagem em alta resolucao.
    cleaned = (
        url.replace("\\u002F", "/")
        .replace("\\/", "/")
        .replace("\\", "")
    )
    cleaned = re.sub(
        r"\._[^./]+_\.(jpg|jpeg|png)",
        r".\1",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


def _fetch_listing_html(detail_url: str) -> str:
    last = ""
    for attempt in range(3):
        try:
            response = requests.get(
                detail_url,
                headers=_listing_headers(),
                timeout=25,
            )
            last = response.text or ""
            if response.status_code == 200 and last:
                return last
        except Exception:
            pass
        time.sleep(2 + attempt)
    return last


def _gallery_scope(html: str) -> str:
    # Isola o array "initial" da galeria principal do produto (ImageBlockATF),
    # ignorando os carrosseis de "produtos relacionados" e os blocos de outras
    # variacoes de cor. A pagina pode ter mais de um array "initial"; escolhe o
    # que tem mais fotos hiRes (a galeria principal do anuncio selecionado).
    best = ""
    best_count = 0

    for marker in re.finditer(r"""['"]initial['"]\s*:\s*\[""", html):
        start = marker.end() - 1
        depth = 0
        end = -1
        limit = min(len(html), start + 200_000)
        for index in range(start, limit):
            char = html[index]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break

        if end == -1:
            continue

        block = html[start:end]
        count = len(
            re.findall(r'"hiRes":"https', block, flags=re.IGNORECASE)
        )
        if count > best_count:
            best_count = count
            best = block

    return best


def _extract_listing_image_urls(html: str) -> list[str]:
    found: list[str] = []
    seen_ids: set[str] = set()

    def _collect(text: str, patterns: tuple[str, ...]) -> None:
        for pattern in patterns:
            for raw in re.findall(pattern, text, flags=re.IGNORECASE):
                url = _clean_image_url(raw)
                if not _listing_image_host_ok(url):
                    continue
                identity = re.search(r"/images/I/([^./]+)", url)
                key = identity.group(1) if identity else url
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                found.append(url)

    # 1) So a galeria principal do anuncio (ordem correta das fotos).
    gallery = _gallery_scope(html)
    if gallery:
        _collect(
            gallery,
            (
                r'"hiRes":"(https:[^"]+?\.(?:jpg|jpeg|png))"',
                r'"large":"(https:[^"]+?\.(?:jpg|jpeg|png))"',
            ),
        )

    # 2) Se nao achou a galeria isolada, usa a foto principal em alta do topo.
    if not found:
        _collect(
            html,
            (
                r'data-old-hires="(https:[^"]+?\.(?:jpg|jpeg|png))"',
                r'"hiRes":"(https:[^"]+?\.(?:jpg|jpeg|png))"',
            ),
        )

    return found


def _extract_listing_video_url(html: str) -> str | None:
    # O JSON da galeria vem HTML-escapado (&quot;) no HTML da Amazon, entao
    # desescapamos antes de procurar. O video DO PRODUTO fica num bloco
    # "isVideo":true (galeria ImageBlock) e a URL costuma ser um HLS .m3u8
    # (as vezes .mp4). Preferimos o video "hero" quando existe e exigimos
    # host media-amazon para nao pegar propaganda de terceiros.
    page = _htmlmod.unescape(html)
    fallback: str | None = None
    for marker in re.finditer(r'"isVideo"\s*:\s*true', page):
        block = page[max(0, marker.start() - 400):marker.end() + 900]
        window = page[marker.end():marker.end() + 900]
        match = re.search(
            r'"url"\s*:\s*"(https:[^"]+?\.(?:m3u8|mp4))"',
            window,
        )
        if not match:
            continue
        candidate = (
            match.group(1)
            .replace("\\u002F", "/")
            .replace("\\/", "/")
        )
        if "media-amazon" not in candidate.lower():
            continue
        if re.search(r'"isHeroVideo"\s*:\s*true', block):
            return candidate
        if fallback is None:
            fallback = candidate
    return fallback


def _download_listing_image(url: str, destination: Path) -> bool:
    if not _listing_image_host_ok(url):
        return False
    try:
        response = requests.get(
            url,
            headers=_listing_headers(),
            timeout=45,
        )
        response.raise_for_status()
    except Exception:
        return False
    content_type = response.headers.get("content-type", "").lower()
    if not content_type.startswith("image/"):
        return False
    data = response.content
    if len(data) < 3_000 or len(data) > 15 * 1024 * 1024:
        return False
    destination.write_bytes(data)
    return True


def _download_listing_video(url: str, work: Path) -> Path | None:
    # O video principal do anuncio costuma ser HLS (.m3u8); o FFmpeg baixa
    # tanto HLS quanto mp4 direto. Pegamos so o VIDEO (a narracao propria e
    # adicionada depois) e limitamos a duracao para nao baixar algo enorme.
    destination = work / "listing_video.mp4"
    user_agent = _listing_headers()["User-Agent"]
    base = [
        _FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-user_agent", user_agent,
        "-i", url,
    ]
    tail_copy = [
        "-map", "0:v:0", "-c:v", "copy", "-an", "-t", "120",
        "-movflags", "+faststart", str(destination),
    ]
    tail_transcode = [
        "-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-an", "-t", "120",
        "-movflags", "+faststart", str(destination),
    ]
    downloaded = False
    for tail in (tail_copy, tail_transcode):
        try:
            completed = subprocess.run(
                base + tail,
                check=False,
                text=True,
                capture_output=True,
                timeout=420,
            )
        except Exception:
            continue
        if (
            completed.returncode == 0
            and destination.is_file()
            and destination.stat().st_size >= 200_000
        ):
            downloaded = True
            break
    if not downloaded:
        return None
    try:
        if duration(destination) < 2.0:
            return None
    except Exception:
        return None
    return destination


def fetch_listing_media(
    product: Any,
    work: Path,
) -> tuple[Path | None, list[Path]]:
    """Baixa a midia REAL do anuncio: (video_ou_None, lista_de_fotos)."""
    detail_url = clean(getattr(product, "detail_url", ""), 1500)

    html = ""
    if detail_url.startswith(("https://", "http://")):
        html = _fetch_listing_html(detail_url)

    image_urls: list[str] = []
    video_url: str | None = None

    if html:
        image_urls = _extract_listing_image_urls(html)
        video_url = _extract_listing_video_url(html)

    # Garante pelo menos a foto principal que ja temos do produto.
    main_image = clean(getattr(product, "image_url", ""), 1500)
    if main_image.startswith(("https://", "http://")):
        cleaned_main = _clean_image_url(main_image)
        if cleaned_main not in image_urls:
            image_urls.insert(0, cleaned_main)

    images: list[Path] = []
    for index, url in enumerate(image_urls[:10]):
        destination = work / f"listing_photo_{index:02d}.jpg"
        if _download_listing_image(url, destination):
            images.append(destination)

    video_path: Path | None = None
    if video_url:
        video_path = _download_listing_video(video_url, work)

    return video_path, images


def _build_listing_slideshow(
    images: list[Path],
    work: Path,
) -> Path:
    """Monta um slideshow 1080x1920 (fundo borrado + foto nitida) das fotos."""
    if not images:
        raise BrollError("O anuncio nao trouxe nenhuma foto utilizavel.")

    # Cada foto fica visivel alguns segundos; o conjunto e repetido depois
    # (via -stream_loop) para cobrir toda a narracao.
    per_image = 3.2

    inputs: list[str] = []
    graph: list[str] = []
    labels: list[str] = []

    for index, image in enumerate(images):
        inputs.extend(
            [
                "-loop",
                "1",
                "-t",
                format(per_image, ".3f"),
                "-i",
                str(image),
            ]
        )
        graph.append(
            f"[{index}:v]split=2[a{index}][b{index}];"
            f"[a{index}]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,gblur=sigma=40:steps=2,"
            f"eq=brightness=-0.20:saturation=0.85,setsar=1[bg{index}];"
            f"[b{index}]scale=1040:1560:force_original_aspect_ratio=decrease,"
            f"setsar=1[fg{index}];"
            f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2,"
            f"fps=30,setsar=1,format=yuv420p[s{index}]"
        )
        labels.append(f"[s{index}]")

    graph.append(
        "".join(labels) + f"concat=n={len(images)}:v=1:a=0[v]"
    )

    filter_path = work / "slides_filter.txt"
    filter_path.write_text(";".join(graph), encoding="utf-8")

    slides_path = work / "listing_slides.mp4"
    run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex_script",
            str(filter_path),
            "-map",
            "[v]",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(slides_path),
        ],
        timeout=1200,
    )

    if not slides_path.is_file() or slides_path.stat().st_size < 100_000:
        raise BrollError(
            "Nao consegui montar o slideshow das fotos do anuncio."
        )

    return slides_path


def render_listing_video(
    product: Any,
    audio_path: Path,
    output_path: Path,
    work_directory: Path,
    report: Any = None,
) -> dict[str, Any]:
    """Renderiza o reel de afiliado usando a MIDIA REAL do anuncio da Amazon."""
    def _sub(fraction: float, stage: str) -> None:
        if not report:
            return
        try:
            report(fraction, stage)
        except Exception:
            pass

    if not audio_path.is_file():
        raise BrollError("A narracao nao foi criada.")

    audio, final_duration = normalize_audio(
        audio_path,
        work_directory,
    )

    _sub(0.25, "baixando fotos e vídeo do anúncio")
    video_path, images = fetch_listing_media(product, work_directory)

    used_video = video_path is not None
    if used_video:
        visual_source = video_path
    else:
        _sub(0.45, "montando as fotos do anúncio")
        visual_source = _build_listing_slideshow(images, work_directory)

    _sub(0.60, "montando legendas e QR")
    story = make_story(product)

    qr_path = work_directory / "product_qr.png"
    detail_url = clean(getattr(product, "detail_url", ""), 1500)
    if not detail_url.startswith(("https://", "http://")):
        raise BrollError("Link do produto invalido.")
    qrcode.make(detail_url).save(qr_path)

    ass_path = work_directory / "captions.ass"
    market = clean(getattr(product, "marketplace_code", ""), 10).upper()
    create_ass(story, final_duration, ass_path, market)

    _sub(0.68, "renderizando vídeo")
    ass_for_filter = str(ass_path).replace("\\", "/").replace(":", "\\:")
    filter_path = work_directory / "filters.txt"

    if used_video:
        # Video do anuncio: fundo borrado (preenche) + video nitido no centro.
        composition = (
            "[0:v]split=2[background_source][foreground_source];"
            "[background_source]scale=1080:1920:"
            "force_original_aspect_ratio=increase,crop=1080:1920,"
            "gblur=sigma=42:steps=3,eq=brightness=-0.22:saturation=0.82,"
            "fps=30,setsar=1,format=yuv420p[background];"
            "[foreground_source]scale=1080:1680:"
            "force_original_aspect_ratio=decrease,fps=30,setsar=1,"
            "format=yuv420p[foreground];"
            "[background]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.12:t=fill"
            "[dark_background];"
            "[dark_background][foreground]overlay=x=(W-w)/2:y=(H-h)/2:"
            "format=auto[composed];"
        )
    else:
        # Slideshow ja vem montado em 1080x1920: so padroniza o formato.
        composition = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,fps=30,setsar=1,format=yuv420p[composed];"
        )

    filter_path.write_text(
        composition
        + "[1:v]scale=245:245,format=rgba[qr];"
        "[composed][qr]overlay=x=(W-w)/2:y=250:format=auto[withqr];"
        "[withqr]subtitles=filename='" + ass_for_filter + "'[v]",
        encoding="utf-8",
    )

    run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(visual_source),
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(qr_path),
            "-i",
            str(audio),
            "-filter_complex_script",
            str(filter_path),
            "-map",
            "[v]",
            "-map",
            "2:a:0",
            "-t",
            format(final_duration, ".3f"),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=1800,
    )

    if (
        not output_path.is_file()
        or output_path.stat().st_size < 300_000
    ):
        raise BrollError("O FFmpeg nao criou um MP4 valido.")

    video_duration = duration(output_path)

    _sub(0.85, "vídeo renderizado")

    return {
        "broll": {
            "source_url": detail_url,
            "title": clean(getattr(product, "title", ""), 300),
            "channel": "amazon_listing",
            "source_duration_seconds": video_duration,
            "license_status": "amazon_product_media",
            "media_kind": (
                "listing_video" if used_video else "listing_photos"
            ),
            "photo_count": 0 if used_video else len(images),
        },
        "broll_path": str(visual_source),
        "story": story,
        "narration": narration_from_story(story),
        "duration_seconds": video_duration,
        "static_image_fallback": not used_video,
        "original_audio_used": False,
    }


def render_live_variant(
    product: Any,
    *,
    broll_path: Path,
    live_audio_path: Path,
    live_narration: str,
    output_path: Path,
    work_directory: Path,
) -> dict[str, Any]:
    """Renderiza a versao de LIVE do produto.

    Reaproveita a MESMA filmagem (b-roll ja baixado para o reels), mas usa a
    NARRACAO da apresentadora (audio de live) e a legenda do que esta sendo
    falado. SEM QR Code e SEM ganchos de reels.
    """
    broll_path = Path(broll_path)
    live_audio_path = Path(live_audio_path)

    if not broll_path.is_file():
        raise BrollError("B-roll da live nao encontrado.")
    if not live_audio_path.is_file():
        raise BrollError("Audio da live nao foi criado.")

    live_duration = duration(live_audio_path)
    if live_duration < 12:
        raise BrollError("Narracao de live muito curta.")
    # Teto de seguranca para nao gerar um bloco gigante.
    live_duration = min(live_duration, 120.0)

    market = clean(getattr(product, "marketplace_code", ""), 10).upper()

    ass_path = work_directory / "captions_live.ass"
    create_live_ass(live_narration, live_duration, ass_path, market)
    ass_for_filter = str(ass_path).replace("\\", "/").replace(":", "\\:")

    filter_path = work_directory / "filters_live.txt"
    filter_path.write_text(
        (
            "[0:v]"
            "split=2"
            "[background_source]"
            "[foreground_source];"

            "[background_source]"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "gblur=sigma=42:steps=3,"
            "eq=brightness=-0.22:saturation=0.82,"
            "fps=30,"
            "setsar=1,"
            "format=yuv420p"
            "[background];"

            "[foreground_source]"
            "scale=1080:1680:force_original_aspect_ratio=decrease,"
            "fps=30,"
            "setsar=1,"
            "format=yuv420p"
            "[foreground];"

            "[background]"
            "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.12:t=fill"
            "[dark_background];"

            "[dark_background]"
            "[foreground]"
            "overlay=x=(W-w)/2:y=(H-h)/2:format=auto"
            "[composed];"

            "[composed]"
            "subtitles=filename='"
            + ass_for_filter
            + "'"
            "[v]"
        ),
        encoding="utf-8",
    )

    run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(broll_path),
            "-i",
            str(live_audio_path),
            "-filter_complex_script",
            str(filter_path),
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-t",
            format(live_duration, ".3f"),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout=1800,
    )

    if (
        not output_path.is_file()
        or output_path.stat().st_size < 200_000
    ):
        raise BrollError("O FFmpeg nao criou a versao de live.")

    return {
        "duration_seconds": duration(output_path),
        "narration": live_narration,
    }