"""Gera a página de bio (link na bio) com os produtos de afiliado publicados.

Uso:
    python scripts/build_bio.py

Lê os produtos publicados do banco (video_assets do tipo AFFILIATE) e escreve
uma página estática em docs/index.html, pronta para o GitHub Pages.
A página não muda a estrutura do Atlas: é só um arquivo HTML.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.product_keyword import product_keyword  # noqa: E402

DOCS_DIR = PROJECT_ROOT / "docs"  # noqa: E402
OUTPUT_FILE = DOCS_DIR / "index.html"
PRODUCTS_JSON = DOCS_DIR / "produtos.json"  # lista que o robo de direct le
# Uniao PERSISTENTE de todos os produtos ja vistos (backup versionado no git).
# Garante que a bio NUNCA perca produtos, mesmo se o banco for zerado.
HISTORICO_FILE = DOCS_DIR / "_bio_historico.json"

# Marca de cada mercado (ajuste os nomes/@ como preferir)
BRANDS = {
    "BR": {"name": "Achados Atlas", "handle": "@achadosatlasbr", "flag": "🇧🇷"},
    "US": {"name": "Atlas Finds", "handle": "@atlasfindsus", "flag": "🇺🇸"},
}

# Links das redes sociais por mercado (@ confirmados com o usuario).
# TikTok confirmado pelo .env; Instagram/Facebook usam o @ publico da conta.
SOCIALS = {
    "BR": {
        "tiktok": "https://www.tiktok.com/@achadosatlasbr",
        "instagram": "https://www.instagram.com/achadosaltas",
        "facebook": "https://www.facebook.com/achadosatlas",
    },
    "US": {
        "tiktok": "https://www.tiktok.com/@atlasfindsus",
        "instagram": "https://www.instagram.com/atlasfindsus",
        "facebook": "https://www.facebook.com/atlasfindsus",
    },
}

# Icones SVG das redes (inline, sem depender de internet).
SOCIAL_ICONS = {
    "tiktok": (
        '<svg viewBox="0 0 24 24"><path d="M16.5 3c.3 2.1 1.5 3.6 3.5 3.9v2.5'
        'c-1.3.1-2.5-.3-3.6-1v5.9c0 3.3-2.4 5.7-5.6 5.7-3 0-5.3-2.2-5.3-5.1 0'
        '-3 2.4-5.2 5.6-5 .3 0 .5 0 .8.1v2.7c-.2-.1-.5-.1-.8-.1-1.4 0-2.6 1-2.6'
        ' 2.4 0 1.4 1.1 2.4 2.5 2.4 1.5 0 2.6-1.1 2.6-2.9V3h2.5z"/></svg>'
    ),
    "instagram": (
        '<svg viewBox="0 0 24 24"><path d="M12 2.2c3.2 0 3.6 0 4.9.1 1.2.1 1.8'
        '.3 2.2.4.6.2 1 .4 1.4.9.5.5.7.9.9 1.4.1.4.3 1 .4 2.2.1 1.3.1 1.7.1 4.9'
        's0 3.6-.1 4.9c-.1 1.2-.3 1.8-.4 2.2-.2.6-.4 1-.9 1.4-.5.5-.9.7-1.4.9-.4'
        '.1-1 .3-2.2.4-1.3.1-1.7.1-4.9.1s-3.6 0-4.9-.1c-1.2-.1-1.8-.3-2.2-.4-.6-.2'
        '-1-.4-1.4-.9-.5-.5-.7-.9-.9-1.4-.1-.4-.3-1-.4-2.2C2.2 15.6 2.2 15.2 2.2 12'
        's0-3.6.1-4.9c.1-1.2.3-1.8.4-2.2.2-.6.4-1 .9-1.4.5-.5.9-.7 1.4-.9.4-.1 1-.3'
        ' 2.2-.4C8.4 2.2 8.8 2.2 12 2.2zm0 3.2A6.6 6.6 0 1 0 12 18.6 6.6 6.6 0 0 0'
        ' 12 5.4zm0 10.9A4.3 4.3 0 1 1 12 7.7a4.3 4.3 0 0 1 0 8.6zm6.8-11.2a1.5 1.5'
        ' 0 1 1-3 0 1.5 1.5 0 0 1 3 0z"/></svg>'
    ),
    "facebook": (
        '<svg viewBox="0 0 24 24"><path d="M22 12a10 10 0 1 0-11.6 9.9v-7H7.9V12h2.5'
        'V9.8c0-2.5 1.5-3.9 3.8-3.9 1.1 0 2.2.2 2.2.2v2.5h-1.3c-1.2 0-1.6.8-1.6 1.6'
        'V12h2.8l-.4 2.9h-2.3v7A10 10 0 0 0 22 12z"/></svg>'
    ),
}

ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)

# Bandeiras desenhadas em SVG (aparecem igual em qualquer aparelho).
FLAG_SVG = {
    "BR": (
        '<svg viewBox="0 0 28 20" preserveAspectRatio="none">'
        '<rect width="28" height="20" fill="#009c3b"/>'
        '<path d="M14 2.4 25.4 10 14 17.6 2.6 10z" fill="#ffdf00"/>'
        '<circle cx="14" cy="10" r="4" fill="#002776"/></svg>'
    ),
    "US": (
        '<svg viewBox="0 0 28 20" preserveAspectRatio="none">'
        '<rect width="28" height="20" fill="#fff"/>'
        '<rect width="28" height="2.86" y="0" fill="#b22234"/>'
        '<rect width="28" height="2.86" y="5.72" fill="#b22234"/>'
        '<rect width="28" height="2.86" y="11.44" fill="#b22234"/>'
        '<rect width="28" height="2.86" y="17.14" fill="#b22234"/>'
        '<rect width="12" height="11.44" fill="#3c3b6e"/></svg>'
    ),
}

# Categorias detectadas por palavras-chave no titulo (ordem = prioridade).
# (chave, emoji, nome_pt, nome_en, [palavras-chave])
CATEGORY_RULES = [
    ("games", "🎮", "Games", "Games",
     ["playstation", "dualsense", "ps5", "ps4", "xbox", "nintendo",
      "gift card", "joystick", "gamepad"]),
    ("beleza", "💄", "Beleza & Cuidados", "Beauty & Care",
     ["shampoo", "condicionador", "sabonete", "hidratante", "creme",
      "cerave", "nivea", "neutrogena", "makeup", "maquiagem", "skincare",
      "loção", "locao", "perfume", "íntimo", "intimo", "barbear", "depila",
      "facial", "corporal", "cabelo"]),
    ("cozinha", "🍳", "Cozinha", "Kitchen",
     ["fritadeira", "air fryer", "liquidificador", "cafeteira", "panela",
      "mixer", "batedeira", "forno", "grill", "cozinha", " faca", "knife",
      "thermometer", "termômetro", "termometro"]),
    ("audio", "🎧", "Áudio", "Audio",
     ["fone", "headphone", "earbud", "airpod", "caixa de som", "soundbar",
      "jbl", "headset"]),
    ("smart", "🏠", "Casa Inteligente", "Smart Home",
     ["alexa", "echo", "fire tv", "chromecast", "google home",
      "lâmpada intelig", "lampada intelig", "smart color", "smart bulb"]),
    ("wearables", "⌚", "Relógios & Wearables", "Watches & Wearables",
     ["smartwatch", "galaxy fit", "apple watch", "relógio", "relogio",
      "pulseira", "smart band", "mi band"]),
    ("fitness", "💪", "Saúde & Fitness", "Health & Fitness",
     ["fitness", "yoga", "pilates", "faixa elástic", "faixa elastic",
      "elástic", "elastic", "massage", "massagem", "academia", "whey",
      "suplement", "oura ring"]),
    ("eletronicos", "📱", "Eletrônicos", "Electronics",
     [" tv", "monitor", "notebook", "tablet", "carregador", " cabo",
      "mouse", "teclado", " ssd", "pen drive", "câmera", "camera",
      "celular", "smartphone", "power bank"]),
]
FALLBACK_CAT = ("outros", "📦", "Outros", "Others")

# Categorias extras que vem da categoria REAL do produto (guardada no payload
# do video_asset). Emoji + nome PT/EN para exibir na bio.
EXTRA_CAT_DISPLAY = {
    "casa": ("🏠", "Casa", "Home"),
    "brinquedos": ("🧸", "Brinquedos", "Toys"),
    "esportes": ("⚽", "Esportes", "Sports"),
    "pet": ("🐾", "Pet", "Pet"),
    "saude": ("🧴", "Saúde", "Health"),
    "escritorio": ("✏️", "Escritório", "Office"),
    "automotivo": ("🚗", "Automotivo", "Automotive"),
    "moda": ("👕", "Moda", "Fashion"),
    "livros": ("📚", "Livros", "Books"),
    "mercado": ("🛒", "Mercado", "Grocery"),
    "instrumentos": ("🎸", "Instrumentos", "Instruments"),
    "eletrodomesticos": ("🔌", "Eletrodomésticos", "Appliances"),
}

# Categoria REAL do produto (slug guardado no payload) -> chave da bio.
# Slugs vindos de app/automation/real_amazon_pipeline.py (CATEGORY_LABELS).
SLUG_TO_KEY = {
    "electronics": "eletronicos",
    "kitchen": "cozinha",
    "home": "casa",
    "beauty": "beleza",
    "toys": "brinquedos",
    "videogames": "games",
    "sports": "esportes",
    "pet-supplies": "pet",
    "hpc": "saude",
    "office-products": "escritorio",
    "automotive": "automotivo",
    "fashion": "moda",
    "books": "livros",
    "grocery": "mercado",
    "musical-instruments": "instrumentos",
    "appliances": "eletrodomesticos",
}

# Fones/caixas de som as vezes chegam como "musical-instruments" na Amazon.
_AUDIO_HINTS = (
    "fone", "headphone", "earbud", "airpod", "headset",
    "caixa de som", "soundbar", "jbl",
)

# Adivinhacao por TITULO cobrindo TODAS as categorias (ordem = prioridade).
# Usada quando o produto nao tem categoria real no payload (ex.: recuperados
# do historico). Primeira regra que casar vence, entao as mais especificas
# vem antes das mais genericas.
TITLE_GUESS_RULES = [
    ("games", ["playstation", "dualsense", "ps5", "ps4", "xbox", "nintendo",
               "gift card", "joystick", "gamepad", "console", "splatoon"]),
    ("audio", ["fone", "headphone", "earbud", "airpod", "headset",
               "caixa de som", "soundbar", "jbl", "speaker"]),
    ("wearables", ["smartwatch", "galaxy fit", "apple watch", "smart band",
                   "mi band", "relógio", "relogio", "pulseira intelig"]),
    ("smart", ["alexa", " echo ", "fire tv", "chromecast", "google home",
               "casa inteligente", "lâmpada intelig", "lampada intelig",
               "smart lâmpada", "smart lampada", "smart bulb", "smart color",
               "tomada intelig", "wi-fi positivo"]),
    ("pet", ["coleira", "antipulga", "antiparasit", "carrapato", "bravecto",
             "scalibor", "ração", "racao", "petisco", " gato", "cachorro",
             "cães", "caes", " cão", "aquário", "aquario", "petshop",
             "dog food", "dog treat", "cat treat", " litter", "dog wrap",
             "poop bag", "pet wipes", "dentastix", "milk-bone", "pedigree",
             "blue buffalo", "greenies", "temptations", "inaba churu",
             "earth rated", "pur luv", "fresh step", "all-absorb",
             "pill pockets", "dog biscuit", "clumping", "for dogs",
             "for cats", "cat food", "dog poop", "poop bags", " leash"]),
    ("automotivo", ["capacete", " moto ", "motocicl", "automotiv", "pneu",
                    "vonixx", "v-mol", "cera automotiva", "para-brisa",
                    "limpa vidro", "óleo motor", "aditivo radiador",
                    "motor oil", "valvoline", "0w-20", "5w-30", "0w-30",
                    "5w-20", "synthetic blend", "windshield", "sun shade",
                    "car mount", "magsafe car", "tesla model"]),
    ("eletrodomesticos", ["ferro de passar", "vaporizador", "aspirador",
                          "sanduicheira", "espremedor", "purificador",
                          "panificadora", "master bread", "geladeira",
                          "fogão", "fogao", "máquina de lavar",
                          "maquina de lavar", "secadora", "ventilador",
                          "climatizador", "torradeira", "enceradeira",
                          "ice maker", "ice machine"]),
    ("cozinha", ["fritadeira", "air fryer", "liquidificador", "cafeteira",
                 "panela", "frigideira", " mixer", "batedeira", " forno",
                 " grill", "cozinha", " faca", "knife", "termômetro",
                 "termometro", "garrafa térmica", "garrafa termica",
                 "coqueteleira", "pote hermétic", "potes hermétic", "tábua",
                 "assadeira", "xícara", "xicara", "water bottle", "tumbler",
                 "quencher", "freesip", "smoothsip", "insulated stainless",
                 "kitchen scale", "food kitchen scale", "can opener",
                 "kitchen shears", "kitchenaid", "hydrojug", "waffle weave",
                 "dish cloth", "coffee tumbler"]),
    ("escritorio", ["papel sulfite", "sulfite", "chamex", "chamequinho",
                    " caneta", "canetinha", " lápis", " lapis", "apontador",
                    "marca texto", "marcador", " estojo", "faber-castell",
                    "pentel", "grafite", "giz de cera", "cd zip", "cd-r",
                    "dvd-r", "fichário", "fichario", "papel a4",
                    "mechanical pencil", "pencils", " pencil", " marker",
                    "highlighter", "sharpie", " expo ", "calculator",
                    "file folder", "laminating", "sheet protector",
                    "printer paper", "copy paper", "copy printer",
                    "ticonderoga", " bic ", "dry erase", "wood-cased"]),
    ("saude", ["creatina", " whey", "ômega", "omega", "colágeno", "colageno",
               "vitamina", "suplement", "glutamina", "bcaa", "maltodextrina",
               "fio dental", "escova de dente", "escova dental", "enxaguante",
               "cicaplast", "protetor solar", "álcool em gel", "alcool em gel",
               "curativo", "band-aid", "multivitam", "probiótic", "probiotic",
               "creatine", "electrolyte", "hydration", "benzoyl peroxide",
               " acne", "pimple patch", "mighty patch", "panoxyl",
               "beet root", "replenisher", "liquid i.v.", "monohydrate"]),
    ("beleza", ["shampoo", "condicionador", "sabonete", "hidratante", " creme",
                "cerave", "nivea", "neutrogena", "makeup", "maquiagem",
                "skincare", "loção", "locao", "perfume", "íntimo", "intimo",
                "barbear", "depila", "facial", "corporal", "cabelo",
                "leave-in", "óleo reparador", "argan", "elseve", "l'oréal",
                "loreal", "lola cosmetics", "sérum", " serum", "esmalte",
                "batom", "rímel", "rimel", "base líquida", "corretivo",
                "body lotion", "body wash", " lotion", "cotton swab",
                "bellacotton", "clean towels", "face towel", "booster",
                "tightening"]),
    ("mercado", ["café", " cafe ", "leite", "ketchup", "danone", " ninho",
                 "nescafé", "nescafe", "dolce gusto", "yopro", "chocolate",
                 "achocolatado", "biscoito", "bolacha", "alimento",
                 "fórmula infantil", "formula infantil", "aptanutri",
                 "arabica", "grãos", "graos", "açúcar", "acucar", " arroz",
                 "feijão", "feijao", "azeite", " molho", "tempero", "cereal",
                 "bebida láctea", "bebida lactea", "heinz", "orfeu",
                 "sparkling water", "sparkling ice", "energy drink",
                 "monster energy", "nespresso", "davinci gourmet",
                 "blueberries", "sparkling"]),
    ("casa", ["amaciante", "desinfetante", "sabão", "sabao", "detergente",
              "lava louças", "lava-louças", "lava louça", "desodorizador",
              "papel higiênico", "higiênico", "higienico", "lysoform",
              " omo ", "downy", " cif ", "finish", "limpeza", "guardanapo",
              "pano reutiliz", "pano de", "vassoura", " rodo", "organizador",
              "toalha de papel", "alvejante", "água sanitária",
              "agua sanitaria", "multiuso", "lustra móveis", "hand soap",
              "mrs. meyer", "toilet paper", "paper plates", "paper towel",
              "moving bags", "hangers", "clothes hanger", "sheets set",
              "bed sheet", "bedding", "fitted sheet", "mattress protector",
              "microfiber cleaning", "cleaning cloth", "odor defense",
              "velvet non-slip", "insect trap", "ant killer", "bait station"]),
    ("moda", ["meia", "meias", "chinelo", "havaianas", "camiseta", " camisa",
              "calça", "calca jeans", "tênis", " tenis", "sapato", "sandália",
              "sandalia", " bota", " roupa", "vestido", "bermuda", "cueca",
              "sutiã", "sutia", "calcinha", "blusa", "jaqueta", "boné",
              " bone ", "óculos de sol", "oculos de sol", "mochila", " bolsa",
              "carteira", " cinto", "t-shirt", "crew t-shirt", "gildan",
              "crocs", " clog", "linen shirt", " shirts", "nipple cover"]),
    ("brinquedos", ["bicicleta de equilibrio", "massa para modelar",
                    "massa de modelar", " das massa", " lego", "boneca",
                    "boneco", "quebra-cabeça", "quebra cabeca", "brinquedo",
                    "pelúcia", "pelucia", "jogo de tabuleiro", "uno original",
                    "carrinho de brinquedo", "playmobil", " pista ", "slime",
                    "baralho", "caiu perdeu"]),
    ("esportes", [" bola ", "futebol", "basquete", "vôlei", "volei",
                  "bicicleta", " bike", "patins", "skate", "corda de pular",
                  "halter", "anilha", "kettlebell", "colchonete", "barraca",
                  "camping", " pesca", "natação", "chuteira", "boxe",
                  "dumbbell", "hand weights", "beach blanket", "beach mat",
                  "dry bag", "waterproof backpack", "yoga mat"]),
    ("instrumentos", ["violão", "violao", "guitarra", "teclado musical",
                      " piano", "ukulele", "cavaco", "pandeiro", "flauta",
                      "cajón", "cajon", "microfone", "guitar strings",
                      "guitar stand", " guitar", "d'addario", "ernie ball",
                      "slinky"]),
    ("fitness", ["fitness", "yoga", "pilates", "faixa elástic",
                 "faixa elastic", "elástic", "elastic", "massage", "massagem",
                 "academia", "oura ring", "esteira", "abdominal"]),
    ("livros", ["edição comemorativa", "edicao comemorativa", " livro",
                " livros", "romance", "editora", "box livros", "a novel",
                " novel ", "dungeon crawler", "hungry caterpillar",
                "project hail mary"]),
    ("eletronicos", [" tv", "monitor", "notebook", "tablet", "carregador",
                     " cabo", " mouse", "teclado", " ssd", "pen drive",
                     "câmera", "camera", "celular", "smartphone", "power bank",
                     "pilha", "pilhas", "bateria", "cr2032", "duracell",
                     "alcalina", "recarregáv", "recarregav", "impressora",
                     "multifuncional", "cartucho", "toner", "adaptador",
                     "hdmi", " usb", "roteador", "filtro de linha", "lanterna",
                     "ink cartridge", "airtag", "aa batteries", "batteries",
                     "microphone cable", " xlr", "blink plus", "hp 67"]),
]

CAT_DISPLAY = {r[0]: (r[1], r[2], r[3]) for r in CATEGORY_RULES}
CAT_DISPLAY.update(EXTRA_CAT_DISPLAY)
CAT_DISPLAY[FALLBACK_CAT[0]] = (FALLBACK_CAT[1], FALLBACK_CAT[2], FALLBACK_CAT[3])
# Ordem de exibicao: regras por titulo, depois as categorias reais, "outros" no fim.
CAT_ORDER = (
    [r[0] for r in CATEGORY_RULES]
    + list(EXTRA_CAT_DISPLAY.keys())
    + [FALLBACK_CAT[0]]
)


def _category(title: str, slug: str | None = None) -> str:
    """Categoria da bio. Prioriza a categoria REAL do produto (slug do
    payload); so quando nao ha categoria real e que adivinha pelo titulo."""
    slug = (slug or "").strip().lower()
    if slug:
        # Fones catalogados como "musical-instruments" vao para Audio.
        if slug == "musical-instruments":
            probe = f" {(title or '').lower()} "
            if any(hint in probe for hint in _AUDIO_HINTS):
                return "audio"
        mapped = SLUG_TO_KEY.get(slug)
        if mapped:
            return mapped
        if slug in CAT_DISPLAY and slug != FALLBACK_CAT[0]:
            return slug
    text = f" {(title or '').lower()} "
    for key, keywords in TITLE_GUESS_RULES:
        if any(kw in text for kw in keywords):
            return key
    return FALLBACK_CAT[0]


def _payload_category(payload: object) -> str:
    """Slug da categoria REAL do produto, guardada no payload do video_asset."""
    if not payload:
        return ""
    data = payload
    if isinstance(data, (str, bytes)):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return ""
    if isinstance(data, dict):
        return str(data.get("category") or "").strip()
    return ""


def _asin_from_url(url: str) -> str | None:
    match = ASIN_RE.search(url or "")
    return match.group(1).upper() if match else None


def _image_urls(asin: str | None) -> list[str]:
    """Varias URLs de imagem da Amazon pela ASIN (o HTML tenta uma por uma)."""
    if not asin:
        return []
    return [
        f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg",
        f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg",
        f"https://m.media-amazon.com/images/P/{asin}.01._SL500_.jpg",
        f"https://images.amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg",
    ]


# Cache em disco das imagens reais da Amazon (evita rebaixar a pagina toda vez).
_IMG_CACHE_FILE = DOCS_DIR / "_img_cache.json"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_IMG_OG_RE = re.compile(
    r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)
_IMG_HIRES_RE = re.compile(r'"hiRes":"(https://[^"]+)"')
_IMG_OLDHIRES_RE = re.compile(r'data-old-hires="(https://[^"]+)"')
_IMG_DYN_RE = re.compile(
    r'data-a-dynamic-image="\{&quot;(https://[^&]+)&quot;'
)
_IMG_LARGE_RE = re.compile(r'"large":"(https://[^"]+)"')


def _load_img_cache() -> dict[str, str]:
    try:
        return json.loads(_IMG_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_img_cache(cache: dict[str, str]) -> None:
    try:
        _IMG_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _fetch_amazon_image(product_url: str) -> str | None:
    """Baixa a imagem REAL (foto) do produto na pagina da Amazon.

    Prioriza a foto da galeria (hiRes/old-hires/dynamic) para o card NUNCA usar
    o poster de um video como imagem; og:image/large ficam so como reserva. O
    padrao P/{asin} devolve pixel vazio para muitos produtos, por isso aqui
    abrimos a pagina e pegamos a imagem verdadeira. Usa cabecalhos completos de
    navegador (com gzip) para nao cair na pagina anti-robo da Amazon.
    """
    import gzip
    import io
    import urllib.request

    headers = {
        "User-Agent": _UA,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    # Foto da galeria PRIMEIRO (evita poster de video); og/large por ultimo.
    regexes = (
        _IMG_HIRES_RE,
        _IMG_OLDHIRES_RE,
        _IMG_DYN_RE,
        _IMG_OG_RE,
        _IMG_LARGE_RE,
    )
    for _ in range(3):
        try:
            req = urllib.request.Request(product_url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                page = raw.decode("utf-8", "ignore")
        except Exception:
            continue
        # Pagina de bloqueio (captcha) vem bem pequena; a real tem centenas de KB.
        low = page.lower()
        if len(page) < 60000 or "automated access" in low or "/errors/" in low:
            continue
        for regex in regexes:
            match = regex.search(page)
            if match:
                return match.group(1)
    return None


def fetch_products() -> dict[str, list[dict]]:
    """Retorna {'BR': [...], 'US': [...]}.

    Entra na bio quem ja foi publicado em PELO MENOS UMA rede (>=1 publicacao
    com sucesso), mesmo com o asset ainda em RETRY_PENDING. A dedup por ASIN
    garante 1 card por produto, entao reenviar o video nao insere de novo.
    """
    query = text(
        """
        SELECT va.id, va.title, va.country_code, va.affiliate_url, va.payload,
               (
                   SELECT c.link_url
                   FROM ad_campaigns c
                   WHERE c.video_asset_id = va.id
                     AND c.status IN (
                         'DRAFT', 'draft', 'REVIEW', 'review',
                         'PAUSED', 'paused', 'ACTIVE', 'active',
                         'CREDENTIALS_MISSING', 'credentials_missing'
                     )
                     AND c.link_url IS NOT NULL
                     AND c.link_url <> ''
                   ORDER BY c.created_at DESC
                   LIMIT 1
               ) AS campaign_url
        FROM video_assets va
        WHERE va.kind = 'AFFILIATE'
          AND va.affiliate_url IS NOT NULL
          AND va.affiliate_url <> ''
          AND (
                va.status IN ('PUBLISHED', 'published')
                OR EXISTS (
                    SELECT 1 FROM publications p
                    WHERE p.video_asset_id = va.id
                      AND p.status = 'PUBLISHED'
                      AND p.external_id IS NOT NULL
                      AND p.external_id <> ''
                )
                OR EXISTS (
                    SELECT 1 FROM ad_campaigns c
                    WHERE c.video_asset_id = va.id
                      AND c.status IN (
                          'DRAFT', 'draft', 'REVIEW', 'review',
                          'PAUSED', 'paused', 'ACTIVE', 'active',
                          'CREDENTIALS_MISSING', 'credentials_missing'
                      )
                )
              )
        ORDER BY va.published_at DESC
        """
    )
    grouped: dict[str, list[dict]] = {"BR": [], "US": []}
    seen: dict[str, set[str]] = {"BR": set(), "US": set()}
    img_cache = _load_img_cache()
    with SessionLocal() as db:
        for asset_id, title, country, url, payload, campaign_url in db.execute(query):
            cc = (country or "").upper()
            if cc not in grouped:
                continue
            asin = _asin_from_url(url)
            # Evita produtos repetidos por ASIN.
            key = asin or url
            if key in seen[cc]:
                continue
            seen[cc].add(key)
            imgs = _image_urls(asin)
            # Imagem REAL da Amazon (og:image) como principal; padrao P/asin
            # fica so como reserva. Usa cache pra nao rebaixar toda vez.
            real = img_cache.get(key)
            if not real:
                real = _fetch_amazon_image(url.strip())
                if real:
                    img_cache[key] = real
            if real:
                imgs = [real] + [u for u in imgs if u != real]
            grouped[cc].append(
                {
                    "asset_id": asset_id,
                    "title": (title or "").strip(),
                    "url": url.strip(),
                    "asin": asin,
                    "image": imgs[0] if imgs else "",
                    "images": imgs,
                    "cat": _category(title, _payload_category(payload)),
                    "campaign_url": (campaign_url or "").strip(),
                }
            )
    _save_img_cache(img_cache)
    return grouped


def _media_ids_by_asset() -> dict[int, dict[str, str]]:
    """{asset_id: {'instagram': post_id, 'facebook': post_id}} das publicacoes.

    O robo usa isso para saber de qual produto e o comentario (pelo post).
    """
    query = text(
        """
        SELECT video_asset_id, platform, external_id
        FROM publications
        WHERE platform IN ('instagram', 'facebook')
          AND external_id IS NOT NULL AND external_id <> ''
        """
    )
    out: dict[int, dict[str, str]] = {}
    with SessionLocal() as db:
        for asset_id, platform, ext in db.execute(query):
            if asset_id is None:
                continue
            out.setdefault(int(asset_id), {})[str(platform)] = str(ext)
    return out


def _load_historico() -> dict[str, dict]:
    """Uniao PERSISTENTE de produtos ja vistos, por chave 'MERCADO:ASIN'."""
    try:
        data = json.loads(HISTORICO_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_historico(hist: dict[str, dict]) -> None:
    try:
        HISTORICO_FILE.write_text(
            json.dumps(hist, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _apply_historico(
    grouped: dict[str, list[dict]],
    media: dict[int, dict[str, str]],
) -> tuple[dict[str, list[dict]], int]:
    """Une os produtos ATUAIS do banco com o historico persistente.

    1) Atualiza o historico com os produtos atuais (categoria REAL + IDs de post).
    2) Adiciona de volta na bio os produtos que sumiram do banco (append-only),
       para a bio NUNCA perder produto por reset/limpeza do banco.
    Devolve (grouped, quantos foram recuperados do historico).
    """
    hist = _load_historico()
    present: dict[str, set[str]] = {"BR": set(), "US": set()}

    # 1) Atualiza o historico com o que esta publicado agora.
    for market, products in grouped.items():
        for p in products:
            asin = p.get("asin") or ""
            ck = asin or p["url"]
            present.setdefault(market, set()).add(ck)
            ids = media.get(int(p["asset_id"]), {}) if p.get("asset_id") else {}
            entry = hist.get(f"{market}:{ck}", {})
            entry.update(
                {
                    "market": market,
                    "asin": asin,
                    "title": p["title"],
                    "url": p["url"],
                    "cat": p.get("cat") or entry.get("cat") or FALLBACK_CAT[0],
                }
            )
            # Nao apaga IDs de post ja conhecidos se agora vierem vazios.
            entry["instagram_media_id"] = (
                ids.get("instagram") or entry.get("instagram_media_id", "")
            )
            entry["facebook_post_id"] = (
                ids.get("facebook") or entry.get("facebook_post_id", "")
            )
            hist[f"{market}:{ck}"] = entry
    _save_historico(hist)

    # 2) Recupera na bio os produtos que estao so no historico (sumiram do banco).
    img_cache = _load_img_cache()
    recovered = 0
    for entry in hist.values():
        market = entry.get("market", "")
        if market not in grouped:
            continue
        url = (entry.get("url") or "").strip()
        asin = entry.get("asin") or _asin_from_url(url)
        ck = asin or url
        if not ck or ck in present.get(market, set()):
            continue
        present[market].add(ck)
        imgs = _image_urls(asin)
        real = img_cache.get(ck)
        if not real:
            real = _fetch_amazon_image(url)
            if real:
                img_cache[ck] = real
        if real:
            imgs = [real] + [u for u in imgs if u != real]
        title = (entry.get("title") or "").strip()
        # Recuperados so tem titulo: se a categoria guardada for "outros"/vazia,
        # tenta adivinhar de novo com as regras atuais (mais completas).
        cat = entry.get("cat") or ""
        if not cat or cat == FALLBACK_CAT[0]:
            cat = _category(title)
        entry["cat"] = cat
        grouped[market].append(
            {
                "asset_id": None,
                "title": title,
                "url": url,
                "asin": asin,
                "image": imgs[0] if imgs else "",
                "images": imgs,
                "cat": cat,
                "ig_media": entry.get("instagram_media_id", ""),
                "fb_media": entry.get("facebook_post_id", ""),
            }
        )
        recovered += 1
    _save_img_cache(img_cache)
    _save_historico(hist)
    return grouped, recovered


def build_products_index(grouped: dict[str, list[dict]]) -> list[dict]:
    """Lista simples que o robo de direct le (palavra -> link do produto)."""
    media = _media_ids_by_asset()
    items: list[dict] = []
    for market, products in grouped.items():
        for p in products:
            ids = media.get(int(p["asset_id"]), {}) if p.get("asset_id") else {}
            ig = ids.get("instagram", "") or p.get("ig_media", "")
            fb = ids.get("facebook", "") or p.get("fb_media", "")
            items.append(
                {
                    "keyword": product_keyword(p["title"], p.get("asin") or ""),
                    "title": p["title"],
                    "url": p["url"],
                    "market": market,
                    "instagram_media_id": ig,
                    "facebook_post_id": fb,
                }
            )
    return items


def _campaign_href(url: str) -> str:
    public_prefix = "https://atlastrends.github.io/atlas-os/"
    if url.startswith(public_prefix):
        return url[len(public_prefix) :].split("?", 1)[0]
    return url


def _card_html(product: dict, cta: str, *, advertised: bool = False) -> str:
    title = html.escape(product["title"])
    title_attr = html.escape(product["title"].lower(), quote=True)
    cat = html.escape(product.get("cat", FALLBACK_CAT[0]), quote=True)
    asin = html.escape(product.get("asin") or "", quote=True)
    destination = (
        _campaign_href(product.get("campaign_url") or product["url"])
        if advertised
        else product["url"]
    )
    url = html.escape(destination, quote=True)
    images = product.get("images") or ([product["image"]] if product.get("image") else [])
    image = html.escape(images[0], quote=True) if images else ""
    srcs = html.escape("|".join(images[1:]), quote=True) if len(images) > 1 else ""
    loading = "eager" if advertised else "lazy"
    img_tag = (
        f'<img class="card-img" src="{image}" alt="{title}" loading="{loading}" '
        f'data-srcs="{srcs}" onerror="imgFallback(this)">'
        if image
        else ""
    )
    card_class = "card advertised-card" if advertised else "card"
    target = "_self" if advertised else "_blank"
    rel = "noopener" if advertised else "nofollow noopener sponsored"
    tracking = "trackAdvertisedProduct(this)" if advertised else "trackAmazonOutbound(this)"
    badge = '<span class="ad-badge">Featured ad</span>' if advertised else ""
    card_id = f"advertised-product-{asin}" if advertised else f"product-{asin}"
    return f"""
      <a class="{card_class}" id="{card_id}" data-asin="{asin}" data-title="{title_attr}" data-cat="{cat}" href="{url}" target="{target}" rel="{rel}" onclick="{tracking}">
        <div class="card-media">{badge}{img_tag}<span class="card-fallback">{title}</span></div>
        <div class="card-info">
          <span class="card-title">{title}</span>
          <span class="card-btn">{cta}</span>
        </div>
      </a>"""


def _socials_html(
    market: str,
    active: bool,
    *,
    social_market: str | None = None,
) -> str:
    links = SOCIALS.get(social_market or market, {})
    parts = []
    for network in ("tiktok", "instagram", "facebook"):
        href = links.get(network)
        if not href:
            continue
        icon = SOCIAL_ICONS[network]
        href_esc = html.escape(href, quote=True)
        parts.append(
            f'<a href="{href_esc}" target="_blank" rel="noopener" '
            f'aria-label="{network}">{icon}</a>'
        )
    cls = "hero-soc active" if active else "hero-soc"
    return f'<div class="{cls}" id="soc-{market}">{"".join(parts)}</div>'


def _catlist_html(market: str, products: list[dict]) -> str:
    counts: dict[str, int] = {}
    for prod in products:
        key = prod.get("cat", FALLBACK_CAT[0])
        counts[key] = counts.get(key, 0) + 1
    all_label = "Todos" if market == "BR" else "All"
    items = [
        f'<button class="cat-item active" data-cat="all" '
        f"onclick=\"selectCat('{market}','all',this)\">"
        f"\U0001f5c2\ufe0f {all_label} <span>{len(products)}</span></button>"
    ]
    for key in CAT_ORDER:
        n = counts.get(key, 0)
        if not n:
            continue
        emoji, name_pt, name_en = CAT_DISPLAY[key]
        name = html.escape(name_pt if market == "BR" else name_en)
        items.append(
            f'<button class="cat-item" data-cat="{key}" '
            f"onclick=\"selectCat('{market}','{key}',this)\">"
            f"{emoji} {name} <span>{n}</span></button>"
        )
    cls = "catlist active" if market == "BR" else "catlist"
    return f'<div class="{cls}" id="cats-{market}">{"".join(items)}</div>'


def build_html(grouped: dict[str, list[dict]]) -> str:
    br = grouped["BR"]
    us = grouped["US"]
    advertised = [
        product
        for market in ("US", "BR")
        for product in grouped[market]
        if product.get("campaign_url")
    ]
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    br_cards = "\n".join(_card_html(p, "Ver na Amazon") for p in br)
    us_cards = "\n".join(_card_html(p, "View on Amazon") for p in us)
    advertised_cards = "\n".join(
        _card_html(p, "View featured page", advertised=True) for p in advertised
    ).strip()
    br_socials = _socials_html("BR", active=True)
    us_socials = _socials_html("US", active=False)
    advertised_socials = _socials_html("ADS", active=False, social_market="US")
    br_cats = _catlist_html("BR", br)
    us_cats = _catlist_html("US", us)
    advertised_cats = _catlist_html("ADS", advertised)
    br_flag = FLAG_SVG["BR"]
    us_flag = FLAG_SVG["US"]

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="index,follow">
<meta name="theme-color" content="#0c0d10">
<title>Achados Atlas · Atlas Finds — Produtos selecionados</title>
<meta name="description" content="Os produtos que aparecem nos nossos vídeos, com link direto para a Amazon.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#0d0d10; --muted:#6b7280; --line:#e7e8ec; --bg:#f5f5f7;
    --brand:#111318; --brand2:#2a2d36;
    --grad:linear-gradient(135deg,#26282f 0%,#0c0d10 100%);
  }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  a {{ -webkit-tap-highlight-color:transparent; }}
  .shell {{ max-width:880px; margin:0 auto; }}
  /* HERO */
  .hero {{
    position:relative; text-align:center; color:#fff; overflow:hidden;
    min-height:300px; display:flex; flex-direction:column; justify-content:flex-end;
    background:var(--grad);
  }}
  .hero-banner {{
    display:none; position:absolute; inset:0; z-index:0;
    width:100%; height:100%; object-fit:cover; object-position:center;
  }}
  .hero-banner.active {{ display:block; }}
  .hero::after {{
    content:""; position:absolute; inset:0; z-index:1; pointer-events:none;
    background:linear-gradient(to top, rgba(8,9,12,.92) 0%, rgba(8,9,12,.55) 26%, rgba(8,9,12,.05) 52%, transparent 70%);
  }}
  .hero-content {{ position:relative; z-index:2; padding:0 22px 24px; }}
  @media (max-width:719px) {{ .hero {{ min-height:210px; }} }}
  /* TOPBAR (abas + busca fixas) */
  .topbar {{
    position:sticky; top:0; z-index:20; padding:12px 16px;
    background:rgba(245,245,247,.92); backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line);
  }}
  .tabs {{ display:flex; gap:8px; }}
  .tab {{
    flex:1; display:flex; align-items:center; justify-content:space-between; gap:6px;
    padding:9px 12px; border:none; border-radius:12px; cursor:pointer;
    background:#fff; color:#5b6472; font-family:"Inter"; font-size:14px; font-weight:600;
    box-shadow:0 2px 6px rgba(15,23,42,.05); transition:all .15s ease;
    text-decoration:none;
  }}
  .tab .tlabel {{ flex:1; text-align:center; }}
  .tab .tflag {{
    flex:0 0 auto; width:22px; height:15px; border-radius:3px; overflow:hidden;
    display:inline-flex; box-shadow:0 0 0 1px rgba(0,0,0,.12); opacity:.7;
  }}
  .tab .tflag svg {{ width:100%; height:100%; display:block; }}
  .tab.active .tflag {{ opacity:1; box-shadow:0 0 0 1px rgba(255,255,255,.55); }}
  .tab.active {{ color:#fff; box-shadow:0 6px 16px rgba(0,0,0,.2); }}
  .tab[data-market="BR"].active {{ background:linear-gradient(135deg,#009c3b 0%,#00701f 100%); box-shadow:0 6px 16px rgba(0,130,45,.34); }}
  .tab[data-market="US"].active {{ background:linear-gradient(135deg,#3c3b6e 0%,#b22234 100%); box-shadow:0 6px 16px rgba(60,59,110,.34); }}
  .tab[data-market="ADS"].active {{ background:var(--grad); box-shadow:0 6px 16px rgba(178,34,52,.28); }}
  .ad-symbol {{
    flex:0 0 auto; width:22px; height:22px; display:inline-flex; align-items:center;
    justify-content:center; border-radius:7px; background:#f2f2f4; font-size:13px;
  }}
  .tab.active .ad-symbol {{ background:rgba(255,255,255,.16); }}
  /* BUSCA + CATEGORIAS */
  .searchrow {{ margin-top:10px; display:flex; gap:8px; align-items:stretch; }}
  .searchbar {{
    flex:1; display:flex; align-items:center; gap:9px; background:#fff;
    border:1px solid var(--line); border-radius:12px; padding:11px 13px;
    box-shadow:0 2px 6px rgba(15,23,42,.05);
  }}
  .searchbar svg {{ width:18px; height:18px; fill:#9aa0ac; flex:0 0 18px; }}
  .searchbar input {{
    border:none; outline:none; width:100%; background:transparent;
    font-family:"Inter"; font-size:14px; color:var(--ink);
  }}
  /* BARRA LATERAL DE CATEGORIAS (sempre visivel) */
  .layout {{ display:flex; gap:18px; align-items:flex-start; padding:20px 16px 10px; }}
  .sidebar {{ flex:0 0 206px; position:sticky; top:calc(var(--topbarH,120px) + 14px); }}
  .sidebar-title {{
    font-family:"Poppins"; font-weight:700; font-size:12px; color:var(--muted);
    text-transform:uppercase; letter-spacing:.6px; margin:0 4px 10px;
  }}
  .catlist {{ display:none; flex-direction:column; gap:6px; }}
  .catlist.active {{ display:flex; }}
  .cat-item {{
    display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%;
    text-align:left; border:1px solid var(--line); background:#fff; padding:10px 12px;
    border-radius:11px; cursor:pointer; font-family:"Inter"; font-size:13.5px; font-weight:600;
    color:var(--ink); white-space:nowrap; box-shadow:0 2px 6px rgba(15,23,42,.04);
  }}
  .cat-item:hover {{ background:#f2f2f4; }}
  .cat-item.active {{ background:var(--grad); color:#fff; border-color:transparent; }}
  .cat-item span {{ font-size:12px; font-weight:600; opacity:.75; }}
  @media (max-width:719px) {{
    .layout {{ flex-direction:column; gap:0; padding:0; }}
    .sidebar {{
      position:sticky; top:var(--topbarH,110px); z-index:15; flex:none; width:100%;
      background:rgba(245,245,247,.94); backdrop-filter:blur(10px);
      padding:9px 12px; border-bottom:1px solid var(--line);
    }}
    .sidebar-title {{ display:none; }}
    .catlist.active {{
      flex-direction:row; overflow-x:auto; gap:8px; padding-bottom:1px;
      -webkit-overflow-scrolling:touch; scrollbar-width:none;
    }}
    .catlist.active::-webkit-scrollbar {{ display:none; }}
    .cat-item {{ width:auto; flex:0 0 auto; }}
  }}
  /* SOCIALS (no hero) */
  .hero-socials {{ position:relative; z-index:1; min-height:44px; }}
  .hero-soc {{ display:none; gap:10px; justify-content:center; }}
  .hero-soc.active {{ display:flex; }}
  .hero-soc a {{
    width:44px; height:44px; border-radius:13px; display:flex; align-items:center;
    justify-content:center; background:rgba(255,255,255,.2); backdrop-filter:blur(6px);
    border:1px solid rgba(255,255,255,.28); transition:transform .15s ease, background .15s ease;
  }}
  .hero-soc a:hover {{ transform:translateY(-2px); background:rgba(255,255,255,.34); }}
  .hero-soc svg {{ width:21px; height:21px; fill:#fff; }}
  /* CONTENT */
  .content {{ flex:1; min-width:0; }}
  @media (max-width:719px) {{ .content {{ padding:16px 16px 10px; }} }}
  .sec-head {{ display:flex; align-items:baseline; justify-content:space-between; margin:2px 4px 16px; }}
  .sec-head h2 {{ font-family:"Poppins"; font-weight:700; font-size:16px; margin:0; }}
  .sec-head span {{ font-size:12.5px; color:var(--muted); }}
  .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:14px; }}
  @media (min-width:560px) {{ .grid {{ grid-template-columns:repeat(3,1fr); }} }}
  .card {{
    display:flex; flex-direction:column; text-decoration:none; background:#fff;
    border:1px solid var(--line); border-radius:18px; overflow:hidden;
    box-shadow:0 4px 14px rgba(15,23,42,.05); transition:transform .16s ease, box-shadow .16s ease;
  }}
  .card:hover {{ transform:translateY(-4px); box-shadow:0 16px 34px rgba(15,23,42,.14); }}
  .card:active {{ transform:translateY(-1px); }}
  .card.featured {{
    outline:4px solid #ff9900;
    box-shadow:0 0 0 7px rgba(255,153,0,.2),0 20px 45px rgba(15,23,42,.2);
    transform:translateY(-4px);
  }}
  .card-media {{
    position:relative; height:190px; background:#f7f8fa; padding:16px;
    display:flex; align-items:center; justify-content:center;
  }}
  .ad-badge {{
    position:absolute; top:10px; left:10px; z-index:2; padding:6px 9px;
    border-radius:9px; color:#fff; background:linear-gradient(135deg,#3c3b6e,#b22234);
    box-shadow:0 4px 12px rgba(60,59,110,.24); font-size:9.5px; font-weight:800;
    letter-spacing:.04em; text-transform:uppercase;
  }}
  .advertised-card {{ box-shadow:0 0 0 2px rgba(178,34,52,.08),0 8px 22px rgba(15,23,42,.09); }}
  .card-img {{ width:100%; height:100%; object-fit:contain; mix-blend-mode:multiply; }}
  .card-fallback {{
    display:none; font-size:11px; color:#fff; font-weight:700; padding:8px;
    text-align:center; line-height:1.25;
  }}
  .card-media.noimg {{ background:var(--grad); }}
  .card-media.noimg .card-fallback {{ display:block; }}
  .card-info {{ display:flex; flex-direction:column; gap:10px; padding:12px 12px 14px; flex:1; }}
  .card-title {{
    font-size:13px; font-weight:600; line-height:1.35; color:var(--ink); min-height:35px;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
  }}
  .card-btn {{
    margin-top:auto; text-align:center; padding:9px 10px; border-radius:11px;
    background:var(--grad); color:#fff; font-size:12.5px; font-weight:700;
    box-shadow:0 4px 12px rgba(0,0,0,.2);
  }}
  .market {{ display:none; }}
  .market.active {{ display:block; animation:fade .25s ease; }}
  @keyframes fade {{ from {{ opacity:0; transform:translateY(6px); }} to {{ opacity:1; transform:none; }} }}
  .empty {{ text-align:center; color:var(--muted); padding:50px 0; grid-column:1/-1; }}
  /* FOOTER */
  .foot {{
    text-align:center; color:#9aa0ac; font-size:11.5px; line-height:1.7;
    padding:30px 20px 54px; max-width:560px; margin:0 auto;
  }}
  .foot strong {{ color:#7b8290; font-weight:600; }}
</style>
</head>
<body>
  <div class="shell">
    <header class="hero">
      <img class="hero-banner active" id="banner-BR" src="banner-br.jpg" alt="Atlas Trends Brasil" fetchpriority="high">
      <img class="hero-banner" id="banner-US" src="banner-us.jpg" alt="Atlas Trends US">
      <img class="hero-banner" id="banner-ADS" src="banner-us.jpg" alt="Atlas Finds advertised products">
      <div class="hero-content">
        <div class="hero-socials">
          {br_socials}
          {us_socials}
          {advertised_socials}
        </div>
      </div>
    </header>

    <nav class="topbar">
      <div class="tabs">
        <button class="tab active" data-market="BR" onclick="showMarket('BR')">
          <span class="tflag">{br_flag}</span><span class="tlabel">Brasil</span><span class="tflag">{br_flag}</span>
        </button>
        <button class="tab" data-market="US" onclick="showMarket('US')">
          <span class="tflag">{us_flag}</span><span class="tlabel">USA</span><span class="tflag">{us_flag}</span>
        </button>
        <button class="tab" data-market="ADS" onclick="showMarket('ADS')">
          <span class="ad-symbol">📣</span><span class="tlabel">Ads</span><span class="ad-symbol">📣</span>
        </button>
        <a class="tab" href="atlas-software/" aria-label="Conheça o software Atlas">
          <span class="ad-symbol">◆</span><span class="tlabel">Software</span><span class="ad-symbol">+</span>
        </a>
      </div>
      <div class="searchrow">
        <div class="searchbar">
          <svg viewBox="0 0 24 24"><path d="M15.5 14h-.8l-.3-.3a6.5 6.5 0 1 0-.7.7l.3.3v.8l5 5 1.5-1.5-5-5zm-6 0A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14z"/></svg>
          <input id="q" type="search" placeholder="Buscar produto..." autocomplete="off" oninput="applyFilter()">
        </div>
      </div>
    </nav>

    <div class="layout">
      <aside class="sidebar">
        <p class="sidebar-title">Categorias</p>
        {br_cats}
        {us_cats}
        {advertised_cats}
      </aside>
      <main class="content">
      <section class="market active" id="market-BR">
        <div class="sec-head">
          <h2>Produtos em destaque</h2>
          <span>{len(br)} itens</span>
        </div>
        <div class="grid">
          {br_cards or '<div class="empty">Em breve novos produtos aqui!</div>'}
          <div class="empty noresult" style="display:none">Nenhum produto encontrado 🔍</div>
        </div>
      </section>

      <section class="market" id="market-US">
        <div class="sec-head">
          <h2>Featured products</h2>
          <span>{len(us)} items</span>
        </div>
        <div class="grid">
          {us_cards or '<div class="empty">New products coming soon!</div>'}
          <div class="empty noresult" style="display:none">No products found 🔍</div>
        </div>
      </section>

      <section class="market" id="market-ADS">
        <div class="sec-head">
          <h2>Advertised products</h2>
          <span>{len(advertised)} {'item' if len(advertised) == 1 else 'items'}</span>
        </div>
        <div class="grid">
          {advertised_cards or '<div class="empty">No advertised products yet.</div>'}
          <div class="empty noresult" style="display:none">No advertised products found 🔍</div>
        </div>
      </section>
      </main>
    </div>

    <footer class="foot">
      <strong>Como afiliado da Amazon, ganhamos com compras qualificadas.</strong><br>
      As an Amazon Associate we earn from qualifying purchases.<br>
      Atualizado em {generated}
    </footer>
  </div>

  <script>
    var catState = {{ BR: 'all', US: 'all', ADS: 'all' }};
    function showMarket(m) {{
      document.querySelectorAll('.market').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'market-' + m);
      }});
      document.querySelectorAll('.tab').forEach(function (el) {{
        el.classList.toggle('active', el.dataset.market === m);
      }});
      document.querySelectorAll('.hero-banner').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'banner-' + m);
      }});
      document.querySelectorAll('.hero-soc').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'soc-' + m);
      }});
      document.querySelectorAll('.catlist').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'cats-' + m);
      }});
      var qEl = document.getElementById('q');
      if (qEl) qEl.placeholder = (m === 'BR') ? 'Buscar produto...' : 'Search product...';
      applyFilter();
      if (history.replaceState) history.replaceState(null, '', '#' + m);
    }}
    function applyFilter() {{
      var q = (document.getElementById('q').value || '').trim().toLowerCase();
      document.querySelectorAll('.market').forEach(function (mk) {{
        var m = mk.id.replace('market-', '');
        var cat = catState[m] || 'all';
        var shown = 0;
        mk.querySelectorAll('.card').forEach(function (c) {{
          var okCat = (cat === 'all') || (c.dataset.cat === cat);
          var okTxt = !q || (c.dataset.title || '').indexOf(q) > -1;
          var hit = okCat && okTxt;
          c.style.display = hit ? '' : 'none';
          if (hit) shown++;
        }});
        var nr = mk.querySelector('.noresult');
        if (nr) nr.style.display = (shown === 0) ? 'block' : 'none';
      }});
    }}
    function selectCat(m, cat, el) {{
      catState[m] = cat;
      var side = document.getElementById('cats-' + m);
      if (side) side.querySelectorAll('.cat-item').forEach(function (b) {{
        b.classList.toggle('active', b === el);
      }});
      applyFilter();
    }}
    // Tenta a proxima URL de imagem da Amazon; se acabarem, mostra o card cinza.
    function imgFallback(img) {{
      var s = (img.getAttribute('data-srcs') || '').split('|').filter(Boolean);
      if (s.length) {{
        img.setAttribute('data-srcs', s.slice(1).join('|'));
        img.src = s[0];
      }} else {{
        img.parentElement.classList.add('noimg');
        img.remove();
      }}
    }}
    // Mede a altura da barra fixa para a lateral colar no lugar certo.
    function fitBars() {{
      var t = document.querySelector('.topbar');
      if (t) document.documentElement.style.setProperty('--topbarH', t.offsetHeight + 'px');
    }}
    window.addEventListener('load', fitBars);
    window.addEventListener('resize', fitBars);
    fitBars();
    function trackAmazonOutbound(card) {{
      if (typeof window.fbq !== 'function') return;
      window.fbq('trackCustom', 'AmazonOutboundClick', {{
        asin: card.dataset.asin || '',
        product_title: card.dataset.title || '',
        market: 'US'
      }});
    }}
    function trackAdvertisedProduct(card) {{
      if (typeof window.fbq !== 'function') return;
      window.fbq('trackCustom', 'AdvertisedProductSelect', {{
        asin: card.dataset.asin || '',
        product_title: card.dataset.title || ''
      }});
    }}
    // Abre mercado e produto exatos quando a campanha usa
    // ?market=US&product=ASIN. O clique Amazon continua voluntario.
    (function () {{
      var params = new URLSearchParams(location.search);
      var requestedMarket = (params.get('market') || '').toUpperCase();
      var requestedProduct = (params.get('product') || '').toUpperCase();
      var h = (location.hash || '').replace('#', '').toUpperCase();
      var market = (requestedMarket === 'US' || requestedMarket === 'BR')
        ? requestedMarket : h;
      if (market === 'US' || market === 'BR' || market === 'ADS') showMarket(market);
      if (!requestedProduct) return;
      var card = document.querySelector(
        '.card[data-asin="' + CSS.escape(requestedProduct) + '"]'
      );
      if (!card) return;
      document.getElementById('q').value = '';
      catState[market || 'US'] = 'all';
      applyFilter();
      card.classList.add('featured');
      card.scrollIntoView({{ behavior:'smooth', block:'center' }});
      if (typeof window.fbq === 'function') {{
        window.fbq('track', 'ViewContent', {{
          content_ids:[requestedProduct],
          content_type:'product'
        }});
      }}
    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    grouped = fetch_products()
    media = _media_ids_by_asset()
    grouped, recuperados = _apply_historico(grouped, media)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_html(grouped), encoding="utf-8")
    # Lista que o robo de direct le (palavra-gatilho -> link do produto).
    index = build_products_index(grouped)
    PRODUCTS_JSON.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "products": index,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"Pagina de bio gerada: {OUTPUT_FILE}\n"
        f"  Brasil: {len(grouped['BR'])} produtos\n"
        f"  USA:    {len(grouped['US'])} produtos\n"
        f"  Recuperados do historico: {recuperados}\n"
        f"Lista do robo: {PRODUCTS_JSON} ({len(index)} produtos)"
    )


if __name__ == "__main__":
    main()
