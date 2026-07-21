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

CAT_DISPLAY = {r[0]: (r[1], r[2], r[3]) for r in CATEGORY_RULES}
CAT_DISPLAY[FALLBACK_CAT[0]] = (FALLBACK_CAT[1], FALLBACK_CAT[2], FALLBACK_CAT[3])
CAT_ORDER = [r[0] for r in CATEGORY_RULES] + [FALLBACK_CAT[0]]


def _category(title: str) -> str:
    text = f" {(title or '').lower()} "
    for key, _emoji, _pt, _en, keywords in CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return key
    return FALLBACK_CAT[0]


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
    """Busca a imagem REAL do produto direto na pagina da Amazon (og:image).

    O padrao P/{asin} da Amazon devolve um pixel vazio para muitos produtos
    (fora de livros/midia), deixando o card sem imagem mesmo com HTTP 200.
    Aqui abrimos a pagina do produto e pegamos a imagem verdadeira, garantindo
    que sempre haja uma imagem valida.
    """
    import urllib.request

    headers = {
        "User-Agent": _UA,
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    # A Amazon alterna entre layouts de pagina; tentamos 2 vezes para pegar
    # um layout que contenha a imagem principal.
    regexes = (
        _IMG_OG_RE,
        _IMG_HIRES_RE,
        _IMG_OLDHIRES_RE,
        _IMG_DYN_RE,
        _IMG_LARGE_RE,
    )
    for _ in range(2):
        try:
            req = urllib.request.Request(product_url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                page = resp.read().decode("utf-8", "ignore")
        except Exception:
            continue
        for regex in regexes:
            match = regex.search(page)
            if match:
                return match.group(1)
    return None


def fetch_products() -> dict[str, list[dict]]:
    """Retorna {'BR': [...], 'US': [...]} com os produtos publicados."""
    query = text(
        """
        SELECT id, title, country_code, affiliate_url
        FROM video_assets
        WHERE kind = 'AFFILIATE'
          AND affiliate_url IS NOT NULL
          AND affiliate_url <> ''
          AND (status = 'PUBLISHED' OR status = 'published')
        ORDER BY published_at DESC
        """
    )
    grouped: dict[str, list[dict]] = {"BR": [], "US": []}
    seen: dict[str, set[str]] = {"BR": set(), "US": set()}
    img_cache = _load_img_cache()
    with SessionLocal() as db:
        for asset_id, title, country, url in db.execute(query):
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
                    "cat": _category(title),
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


def build_products_index(grouped: dict[str, list[dict]]) -> list[dict]:
    """Lista simples que o robo de direct le (palavra -> link do produto)."""
    media = _media_ids_by_asset()
    items: list[dict] = []
    for market, products in grouped.items():
        for p in products:
            ids = media.get(int(p["asset_id"]), {}) if p.get("asset_id") else {}
            items.append(
                {
                    "keyword": product_keyword(p["title"], p.get("asin") or ""),
                    "title": p["title"],
                    "url": p["url"],
                    "market": market,
                    "instagram_media_id": ids.get("instagram", ""),
                    "facebook_post_id": ids.get("facebook", ""),
                }
            )
    return items


def _card_html(product: dict, cta: str) -> str:
    title = html.escape(product["title"])
    title_attr = html.escape(product["title"].lower(), quote=True)
    cat = html.escape(product.get("cat", FALLBACK_CAT[0]), quote=True)
    url = html.escape(product["url"], quote=True)
    images = product.get("images") or ([product["image"]] if product.get("image") else [])
    image = html.escape(images[0], quote=True) if images else ""
    srcs = html.escape("|".join(images[1:]), quote=True) if len(images) > 1 else ""
    img_tag = (
        f'<img class="card-img" src="{image}" alt="{title}" loading="lazy" '
        f'data-srcs="{srcs}" onerror="imgFallback(this)">'
        if image
        else ""
    )
    return f"""
      <a class="card" data-title="{title_attr}" data-cat="{cat}" href="{url}" target="_blank" rel="nofollow noopener sponsored">
        <div class="card-media">{img_tag}<span class="card-fallback">{title}</span></div>
        <div class="card-info">
          <span class="card-title">{title}</span>
          <span class="card-btn">{cta}</span>
        </div>
      </a>"""


def _socials_html(market: str, active: bool) -> str:
    links = SOCIALS.get(market, {})
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
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    br_cards = "\n".join(_card_html(p, "Ver na Amazon") for p in br)
    us_cards = "\n".join(_card_html(p, "View on Amazon") for p in us)
    br_socials = _socials_html("BR", active=True)
    us_socials = _socials_html("US", active=False)
    br_cats = _catlist_html("BR", br)
    us_cats = _catlist_html("US", us)
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
    position:relative; text-align:center; color:#fff; padding:44px 22px 30px;
    background:var(--grad); overflow:hidden;
  }}
  .hero::after {{
    content:""; position:absolute; inset:0; pointer-events:none;
    background:radial-gradient(120% 90% at 50% -20%, rgba(255,255,255,.35), transparent 60%);
  }}
  .avatar {{
    position:relative; z-index:1; width:96px; height:96px; border-radius:50%;
    margin:0 auto 16px; background:#fff; color:#111318;
    display:flex; align-items:center; justify-content:center;
    font-family:"Poppins"; font-weight:800; font-size:42px;
    box-shadow:0 12px 30px rgba(0,0,0,.22); border:4px solid rgba(255,255,255,.65);
  }}
  .hero h1 {{
    position:relative; z-index:1; font-family:"Poppins"; font-weight:700;
    font-size:25px; margin:0 0 6px; letter-spacing:-.3px;
  }}
  .hero .tag {{ position:relative; z-index:1; margin:0; font-size:14.5px; opacity:.95; }}
  .badge {{
    position:relative; z-index:1; display:inline-flex; align-items:center; gap:6px;
    margin-top:14px; padding:6px 14px; border-radius:999px; font-size:12.5px;
    font-weight:600; background:rgba(255,255,255,.2); backdrop-filter:blur(6px);
  }}
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
  .hero-socials {{ position:relative; z-index:1; margin-top:16px; min-height:44px; }}
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
  .card-media {{
    position:relative; height:190px; background:#f7f8fa; padding:16px;
    display:flex; align-items:center; justify-content:center;
  }}
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
      <div class="avatar">A</div>
      <h1>Achados Atlas · Atlas Finds</h1>
      <p class="tag">Curadoria dos produtos que aparecem nos nossos vídeos 🎬</p>
      <span class="badge">✨ {len(br) + len(us)} produtos selecionados</span>
      <div class="hero-socials">
        {br_socials}
        {us_socials}
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
      </main>
    </div>

    <footer class="foot">
      <strong>Como afiliado da Amazon, ganhamos com compras qualificadas.</strong><br>
      As an Amazon Associate we earn from qualifying purchases.<br>
      Atualizado em {generated}
    </footer>
  </div>

  <script>
    var catState = {{ BR: 'all', US: 'all' }};
    function showMarket(m) {{
      document.querySelectorAll('.market').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'market-' + m);
      }});
      document.querySelectorAll('.tab').forEach(function (el) {{
        el.classList.toggle('active', el.dataset.market === m);
      }});
      document.querySelectorAll('.hero-soc').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'soc-' + m);
      }});
      document.querySelectorAll('.catlist').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'cats-' + m);
      }});
      var qEl = document.getElementById('q');
      if (qEl) qEl.placeholder = (m === 'US') ? 'Search product...' : 'Buscar produto...';
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
    // Abre direto na aba certa se a URL terminar com #US ou #BR.
    (function () {{
      var h = (location.hash || '').replace('#', '').toUpperCase();
      if (h === 'US' || h === 'BR') showMarket(h);
    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    grouped = fetch_products()
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
        f"Lista do robo: {PRODUCTS_JSON} ({len(index)} produtos)"
    )


if __name__ == "__main__":
    main()
