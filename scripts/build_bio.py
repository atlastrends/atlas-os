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
        <div class="card-thumb">{img_tag}<span class="card-fallback">{title}</span></div>
        <div class="card-body">
          <span class="card-title">{title}</span>
          <span class="card-cta">{cta}</span>
        </div>
      </a>"""


def build_html(grouped: dict[str, list[dict]]) -> str:
    br = grouped["BR"]
    us = grouped["US"]
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    br_cards = "\n".join(_card_html(p, "🛒 Comprar na Amazon") for p in br)
    us_cards = "\n".join(_card_html(p, "🛒 Buy on Amazon") for p in us)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="index,follow">
<title>Achados Atlas / Atlas Finds — Produtos</title>
<style>
  :root {{
    --bg:#0e0f13; --card:#1a1c22; --card2:#22252d; --text:#f5f6f8;
    --muted:#9aa0ac; --accent:#ff9900; --accent2:#ffb84d;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:620px; margin:0 auto; padding:24px 16px 60px; }}
  .head {{ text-align:center; margin-bottom:20px; }}
  .logo {{
    width:78px; height:78px; border-radius:50%; margin:0 auto 12px;
    background:linear-gradient(135deg,var(--accent),#ff5e00);
    display:flex; align-items:center; justify-content:center;
    font-size:34px; font-weight:800; color:#111;
  }}
  .head h1 {{ font-size:22px; margin:0 0 2px; }}
  .head p {{ color:var(--muted); margin:0; font-size:14px; }}
  .tabs {{ display:flex; gap:8px; margin:18px 0 22px; }}
  .tab {{
    flex:1; padding:12px; border:none; border-radius:14px; cursor:pointer;
    background:var(--card); color:var(--text); font-size:15px; font-weight:600;
  }}
  .tab.active {{ background:var(--accent); color:#111; }}
  .grid {{ display:flex; flex-direction:column; gap:12px; }}
  .card {{
    display:flex; align-items:center; gap:14px; text-decoration:none;
    background:var(--card); border-radius:16px; padding:12px; color:var(--text);
    transition:transform .08s ease, background .15s ease;
  }}
  .card:active {{ transform:scale(.985); }}
  .card:hover {{ background:var(--card2); }}
  .card-thumb {{
    width:72px; height:72px; flex:0 0 72px; border-radius:12px; overflow:hidden;
    background:#fff; display:flex; align-items:center; justify-content:center; position:relative;
  }}
  .card-img {{ width:100%; height:100%; object-fit:contain; }}
  .card-fallback {{
    display:none; font-size:10px; color:#333; padding:4px; text-align:center;
    line-height:1.15; overflow:hidden;
  }}
  .card-thumb.noimg {{ background:linear-gradient(135deg,var(--accent2),var(--accent)); }}
  .card-thumb.noimg .card-fallback {{ display:block; color:#111; font-weight:700; }}
  .card-body {{ display:flex; flex-direction:column; gap:6px; min-width:0; }}
  .card-title {{
    font-size:14px; font-weight:600; line-height:1.3;
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
  }}
  .card-cta {{ font-size:12px; font-weight:700; color:var(--accent); }}
  .market {{ display:none; }}
  .market.active {{ display:block; }}
  .empty {{ text-align:center; color:var(--muted); padding:40px 0; }}
  .foot {{ text-align:center; color:var(--muted); font-size:11px; margin-top:34px; line-height:1.5; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div class="logo">A</div>
      <h1>Achados Atlas · Atlas Finds</h1>
      <p>Os produtos que aparecem nos nossos vídeos 👇</p>
    </div>

    <div class="tabs">
      <button class="tab active" data-market="BR" onclick="showMarket('BR')">🇧🇷 Brasil</button>
      <button class="tab" data-market="US" onclick="showMarket('US')">🇺🇸 USA</button>
    </div>

    <div class="market active" id="market-BR">
      <div class="grid">
        {br_cards or '<div class="empty">Em breve novos produtos aqui!</div>'}
      </div>
    </div>

    <div class="market" id="market-US">
      <div class="grid">
        {us_cards or '<div class="empty">New products coming soon!</div>'}
      </div>
    </div>

    <div class="foot">
      Como afiliado da Amazon, ganhamos com compras qualificadas.<br>
      As an Amazon Associate we earn from qualifying purchases.<br>
      Atualizado em {generated}
    </div>
  </div>

  <script>
    function showMarket(m) {{
      document.querySelectorAll('.market').forEach(function (el) {{
        el.classList.toggle('active', el.id === 'market-' + m);
      }});
      document.querySelectorAll('.tab').forEach(function (el) {{
        el.classList.toggle('active', el.dataset.market === m);
      }});
    }}
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
