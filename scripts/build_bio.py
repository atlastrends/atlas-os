"""Gera a página de bio (link na bio) com os produtos de afiliado publicados.

Uso:
    python scripts/build_bio.py

Lê os produtos publicados do banco (video_assets do tipo AFFILIATE) e escreve
uma página estática em docs/index.html, pronta para o GitHub Pages.
A página não muda a estrutura do Atlas: é só um arquivo HTML.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

DOCS_DIR = PROJECT_ROOT / "docs"  # noqa: E402
OUTPUT_FILE = DOCS_DIR / "index.html"

# Marca de cada mercado (ajuste os nomes/@ como preferir)
BRANDS = {
    "BR": {"name": "Achados Atlas", "handle": "@achadosatlasbr", "flag": "🇧🇷"},
    "US": {"name": "Atlas Finds", "handle": "@atlasfindsus", "flag": "🇺🇸"},
}

# Links das redes sociais por mercado. AJUSTE aqui se algum estiver diferente.
SOCIALS = {
    "BR": {
        "tiktok": "https://www.tiktok.com/@achadosatlasbr",
        "instagram": "https://www.instagram.com/achadosatlasbr",
        "facebook": "https://www.facebook.com/achadosatlasbr",
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


def _asin_from_url(url: str) -> str | None:
    match = ASIN_RE.search(url or "")
    return match.group(1).upper() if match else None


def _image_url(asin: str | None) -> str:
    if not asin:
        return ""
    # Imagem pública do produto pela ASIN (com fallback no HTML se falhar).
    return f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"


def fetch_products() -> dict[str, list[dict]]:
    """Retorna {'BR': [...], 'US': [...]} com os produtos publicados."""
    query = text(
        """
        SELECT title, country_code, affiliate_url
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
    with SessionLocal() as db:
        for title, country, url in db.execute(query):
            cc = (country or "").upper()
            if cc not in grouped:
                continue
            asin = _asin_from_url(url)
            # Evita produtos repetidos por ASIN.
            key = asin or url
            if key in seen[cc]:
                continue
            seen[cc].add(key)
            grouped[cc].append(
                {
                    "title": (title or "").strip(),
                    "url": url.strip(),
                    "asin": asin,
                    "image": _image_url(asin),
                }
            )
    return grouped


def _card_html(product: dict, cta: str) -> str:
    title = html.escape(product["title"])
    url = html.escape(product["url"], quote=True)
    image = html.escape(product["image"], quote=True)
    img_tag = (
        f'<img class="card-img" src="{image}" alt="{title}" loading="lazy" '
        f"onerror=\"this.parentElement.classList.add('noimg');this.remove();\">"
        if image
        else ""
    )
    return f"""
      <a class="card" href="{url}" target="_blank" rel="nofollow noopener sponsored">
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


def build_html(grouped: dict[str, list[dict]]) -> str:
    br = grouped["BR"]
    us = grouped["US"]
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    br_cards = "\n".join(_card_html(p, "Ver na Amazon") for p in br)
    us_cards = "\n".join(_card_html(p, "View on Amazon") for p in us)
    br_socials = _socials_html("BR", active=True)
    us_socials = _socials_html("US", active=False)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="index,follow">
<meta name="theme-color" content="#ff5e00">
<title>Achados Atlas · Atlas Finds — Produtos selecionados</title>
<meta name="description" content="Os produtos que aparecem nos nossos vídeos, com link direto para a Amazon.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#12141a; --muted:#6b7280; --line:#eceef2; --bg:#f4f5f7;
    --brand:#ff7a00; --brand2:#ff2d6f;
    --grad:linear-gradient(135deg,#ff9d00 0%,#ff5e00 52%,#ff2d6f 100%);
  }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  a {{ -webkit-tap-highlight-color:transparent; }}
  .shell {{ max-width:760px; margin:0 auto; }}
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
    margin:0 auto 16px; background:#fff; color:#ff5e00;
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
  /* TABS */
  .tabs {{
    position:sticky; top:0; z-index:20; display:flex; gap:8px;
    padding:12px 16px; background:rgba(244,245,247,.9); backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line);
  }}
  .tab {{
    flex:1; padding:11px 10px; border:none; border-radius:12px; cursor:pointer;
    background:#fff; color:#5b6472; font-family:"Inter"; font-size:14px; font-weight:600;
    box-shadow:0 2px 6px rgba(15,23,42,.05); transition:all .15s ease;
  }}
  .tab.active {{ background:var(--grad); color:#fff; box-shadow:0 6px 16px rgba(255,94,0,.32); }}
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
  .content {{ padding:20px 16px 10px; }}
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
    position:relative; aspect-ratio:1/1; background:#f7f8fa; padding:14px;
    display:flex; align-items:center; justify-content:center;
  }}
  .card-img {{ max-width:100%; max-height:100%; object-fit:contain; mix-blend-mode:multiply; }}
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
    box-shadow:0 4px 12px rgba(255,94,0,.28);
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

    <nav class="tabs">
      <button class="tab active" data-market="BR" onclick="showMarket('BR')">🇧🇷 Brasil</button>
      <button class="tab" data-market="US" onclick="showMarket('US')">🇺🇸 USA</button>
    </nav>

    <main class="content">
      <section class="market active" id="market-BR">
        <div class="sec-head">
          <h2>Produtos em destaque</h2>
          <span>{len(br)} itens</span>
        </div>
        <div class="grid">
          {br_cards or '<div class="empty">Em breve novos produtos aqui!</div>'}
        </div>
      </section>

      <section class="market" id="market-US">
        <div class="sec-head">
          <h2>Featured products</h2>
          <span>{len(us)} items</span>
        </div>
        <div class="grid">
          {us_cards or '<div class="empty">New products coming soon!</div>'}
        </div>
      </section>
    </main>

    <footer class="foot">
      <strong>Como afiliado da Amazon, ganhamos com compras qualificadas.</strong><br>
      As an Amazon Associate we earn from qualifying purchases.<br>
      Atualizado em {generated}
    </footer>
  </div>

  <script>
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
      if (history.replaceState) history.replaceState(null, '', '#' + m);
    }}
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
    print(
        f"Pagina de bio gerada: {OUTPUT_FILE}\n"
        f"  Brasil: {len(grouped['BR'])} produtos\n"
        f"  USA:    {len(grouped['US'])} produtos"
    )


if __name__ == "__main__":
    main()
