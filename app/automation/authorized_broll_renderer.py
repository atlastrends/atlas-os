from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import re
import shutil
import subprocess
import sys
import time

import qrcode


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
        "pain": "você quer resolver um problema da rotina sem gastar dinheiro na opção errada",
        "benefit": "tornar uma tarefa recorrente mais simples e prática",
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
            "you want to solve an everyday problem without wasting "
            "money on the wrong option"
        ),
        "benefit": (
            "make a recurring task simpler and more convenient"
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
    if price:
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
        lines.append("Caracteristicas do anuncio:")
        for item in clean_features[:6]:
            lines.append(f"- {item}")

    description = clean(getattr(product, "description", ""), 600)
    if description:
        lines.append(f"Descricao: {description}")

    return "\n".join(lines)


def _story_prompt(product: Any, market: str) -> str:
    facts = _product_facts(product)

    if market == "US":
        return (
            "You are a top-tier short-form video copywriter for an Amazon "
            "affiliate channel. Write a punchy, SPECIFIC 6-scene script in "
            "ENGLISH for a 45-55 second vertical video about the product "
            "below. The script MUST be about THIS exact product, using its "
            "real details.\n\n"
            f"PRODUCT DATA (from the Amazon listing):\n{facts}\n\n"
            "RULES:\n"
            "- Be specific to THIS product. Reference its real features/use.\n"
            "- Strong hook in scene 1 (pattern interrupt, create curiosity).\n"
            "- Do NOT invent specs that are not in the data above.\n"
            "- Do NOT mention discounts, sales, 'lowest price' or guarantees.\n"
            "- Natural creator tone, not corporate. No emojis in 'voice'.\n"
            "- Scene 5 must tell viewers to scan the QR code to see the full, "
            "updated listing (mention the price can change).\n"
            "- Scene 6 is a call to follow for new daily finds.\n"
            "- 'caption' = 3-6 word UPPERCASE on-screen hook for that scene.\n"
            "- 'voice' = 1-2 spoken sentences for that scene.\n"
            "- Return ONLY valid JSON, no markdown, in this exact shape:\n"
            '{"scenes":[{"caption":"...","voice":"..."}, ... 6 items]}'
        )

    return (
        "Voce e um copywriter TOP de video curto para um canal de afiliados "
        "da Amazon. Escreva um roteiro ESPECIFICO e chamativo, com 6 cenas, "
        "em PORTUGUES DO BRASIL, para um video vertical de 45 a 55 segundos "
        "sobre o produto abaixo. O roteiro TEM que ser sobre ESTE produto "
        "exato, usando os detalhes reais dele.\n\n"
        f"DADOS DO PRODUTO (do anuncio da Amazon):\n{facts}\n\n"
        "REGRAS:\n"
        "- Seja especifico DESTE produto. Cite caracteristicas/usos reais.\n"
        "- Gancho forte na cena 1 (quebra de padrao, gera curiosidade).\n"
        "- NAO invente especificacoes que nao estao nos dados acima.\n"
        "- NAO fale de desconto, promocao, 'menor preco' nem garantia.\n"
        "- Tom de criador de conteudo, natural. Sem emojis no 'voice'.\n"
        "- A cena 5 deve pedir para escanear o QR Code e ver o anuncio "
        "completo e atualizado (diga que o preco pode mudar).\n"
        "- A cena 6 e um convite para seguir e ver achados novos todo dia.\n"
        "- 'caption' = gancho de 3 a 6 palavras em MAIUSCULAS para a cena.\n"
        "- 'voice' = 1 a 2 frases faladas para a cena.\n"
        "- Retorne SOMENTE JSON valido, sem markdown, neste formato exato:\n"
        '{"scenes":[{"caption":"...","voice":"..."}, ... 6 itens]}'
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


def _groq_story_text(prompt: str) -> str | None:
    """Tenta gerar o roteiro (JSON) com o Groq. Retorna o texto cru ou None."""
    service = _content_service()
    if service is None or getattr(service, "client", None) is None:
        return None

    try:
        model = service._get_best_model()
    except Exception:
        model = "llama-3.3-70b-versatile"

    try:
        response = service.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You output ONLY valid JSON, no markdown, no comments. "
                        "You are an elite short-form affiliate video copywriter."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=1400,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        print(f"[BROLL] Groq falhou no roteiro: {exc}")
        return None

    try:
        return response.choices[0].message.content
    except Exception:
        return None


def _llm_story(product: Any, market: str) -> list[dict[str, str]] | None:
    """Gera o roteiro com IA a partir dos dados reais do produto Amazon.

    Tenta Gemini e, se faltar cota, cai no Groq. Retorna None se ambos
    falharem (usa o template). Desligavel com AFFILIATE_LLM_SCRIPT=0.
    """
    if (os.getenv("AFFILIATE_LLM_SCRIPT") or "1").strip().lower() in {
        "0", "false", "no", "off"
    }:
        return None

    prompt = _story_prompt(product, market)

    for provider, generator in (
        ("gemini", _gemini_story_text),
        ("groq", _groq_story_text),
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
            print(
                f"[BROLL] Roteiro especifico gerado pela IA ({provider}): {title}"
            )
            return scenes[:6]

    print("[BROLL] IA sem cota/indisponivel, usando template especifico.")
    return None



def make_story(product: Any) -> list[dict[str, str]]:
    title = short_title(product)
    profile = product_profile(product)
    feature = verified_feature(product)
    price = clean(
        getattr(product, "price_display", ""),
        60,
    )

    market = clean(
        getattr(product, "marketplace_code", ""),
        10,
    ).upper()

    if market == "US":
        profile = english_product_profile(
            product
        )

    ai_story = _llm_story(product, market)
    if ai_story:
        return ai_story

    if market == "US":
        return [
            {
                "caption": "STOP — DON'T WASTE YOUR MONEY",
                "voice": (
                    f"Stop scrolling for three seconds. If {profile['pain']}, "
                    "you need to see this before you buy the wrong thing."
                ),
            },
            {
                "caption": "HERE'S WHAT IT ACTUALLY DOES",
                "voice": (
                    f"This is the {title}. It's built to help you "
                    f"{profile['benefit']} — simple as that."
                ),
            },
            {
                "caption": "THE DETAIL THAT CHANGES EVERYTHING",
                "voice": (
                    f"Straight from the listing: {feature}."
                    if feature
                    else
                    "The real win isn't a flashy promise. It's making a task "
                    "you repeat every single day genuinely easier."
                ),
            },
            {
                "caption": "ALMOST NOBODY CHECKS THIS",
                "voice": (
                    f"Before you buy, compare {profile['check']}. "
                    "That one habit separates a smart buy from a regret."
                ),
            },
            {
                "caption": "SEE THE LISTING BEFORE IT CHANGES",
                "voice": (
                    (
                        f"Right now the listing shows {price}, but price and "
                        "availability can change fast. "
                    )
                    if price
                    else
                    "Price and availability can change fast. "
                )
                + "Scan the QR code and check the full, updated listing now."
            },
            {
                "caption": "NEW FINDS EVERY SINGLE DAY",
                "voice": (
                    "Follow now and turn on notifications — fresh product "
                    "finds drop every single day."
                ),
            },
        ]

    return [
        {
            "caption": "PARA TUDO — NÃO ERRE ESSA COMPRA",
            "voice": (
                f"Para de rolar o feed por três segundos. Se {profile['pain']}, "
                "você precisa ver isso antes de gastar seu dinheiro à toa."
            ),
        },
        {
            "caption": "O QUE ISSO RESOLVE DE VERDADE",
            "voice": (
                f"Esse é o {title}. Ele foi feito pra te ajudar a "
                f"{profile['benefit']} — sem enrolação."
            ),
        },
        {
            "caption": "O DETALHE QUE FAZ A DIFERENÇA",
            "voice": (
                f"Direto do anúncio: {feature}."
                if feature
                else
                "A vantagem de verdade não é uma promessa mirabolante. É deixar "
                "uma tarefa do seu dia a dia muito mais fácil."
            ),
        },
        {
            "caption": "QUASE NINGUÉM REPARA NISSO",
            "voice": (
                f"Antes de comprar, compare {profile['check']}. "
                "É esse cuidado que separa quem acerta de quem se arrepende."
            ),
        },
        {
            "caption": "OLHA O ANÚNCIO ANTES QUE MUDE",
            "voice": (
                (
                    f"Agora o anúncio mostra {price}, mas preço e "
                    "disponibilidade podem mudar rápido. "
                )
                if price
                else
                "Preço e disponibilidade podem mudar rápido. "
            )
            + "Escaneia o QR Code e confere o anúncio completo e atualizado."
        },
        {
            "caption": "ACHADOS NOVOS TODO DIA",
            "voice": (
                "Segue a gente e ativa as notificações: tem produto novo todo dia."
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


def choose_candidate(product: Any) -> dict[str, Any]:
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

    if not ranked:
        # Plano B: a busca ja mirou o produto vendido, entao em vez de
        # falhar pegamos o melhor resultado relevante encontrado.
        if fallback:
            fallback.sort(
                key=lambda item: item[0],
                reverse=True,
            )
            return fallback[0][1]

        if allowed:
            raise BrollError(
                "Nenhum video relacionado foi encontrado nos canais aprovados."
            )
        raise BrollError(
            "Nenhum video relacionado foi encontrado no YouTube."
        )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return ranked[0][1]


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


def normalize_audio(
    source: Path,
    work: Path,
) -> tuple[Path, float]:
    original_duration = duration(source)

    if 30 <= original_duration <= 60:
        return source, original_duration

    output = work / "voice_normalized.m4a"

    if original_duration < 30:
        speed = max(0.5, original_duration / 34.0)
    else:
        speed = original_duration / 54.0

    filters: list[str] = []

    while speed > 2:
        filters.append("atempo=2.0")
        speed /= 2

    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5

    filters.append(
        "atempo=" + format(speed, ".5f")
    )

    run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-af",
            ",".join(filters),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output),
        ],
        timeout=300,
    )

    final_duration = duration(output)

    if final_duration < 30 or final_duration > 60:
        raise BrollError(
            "A narracao nao pode ser ajustada para 30 a 60 segundos."
        )

    return output, final_duration


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


def render_authorized_video(
    product: Any,
    audio_path: Path,
    output_path: Path,
    work_directory: Path,
) -> dict[str, Any]:
    if not audio_path.is_file():
        raise BrollError("A narracao nao foi criada.")

    audio, final_duration = normalize_audio(
        audio_path,
        work_directory,
    )

    candidate = choose_candidate(product)
    broll = download_broll(
        candidate,
        work_directory,
    )

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
            "y=185:"
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

    return {
        "broll": {
            "source_url": broll["source_url"],
            "title": broll["title"],
            "channel": broll["channel"],
            "source_duration_seconds": broll["source_duration_seconds"],
            "license_status": broll["license_status"],
        },
        "story": story,
        "narration": narration_from_story(story),
        "duration_seconds": video_duration,
        "static_image_fallback": False,
        "original_audio_used": False,
    }