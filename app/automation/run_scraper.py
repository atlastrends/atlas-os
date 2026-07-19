import json
import os
import hashlib
import requests
import re
from pathlib import Path
import time

# Categorias disponiveis (slug da Amazon -> nome exibido no painel).
# Usamos a pagina "Mais Vendidos / Best Sellers" de cada categoria (essa
# pagina traz os produtos no proprio HTML, entao da para ler direto).
# Obs.: a pagina "Em Alta / Movers & Shakers" carrega por JavaScript e nao
# pode ser lida por este raspador simples.
CATEGORIES = {
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

# Em alguns mercados a lista geral da categoria nao faz jus ao nome. Ex.: nos
# EUA "hpc" e' "Health & Household" (Saude e Utilidades Domesticas) e a lista
# e' dominada por PILHAS e PAPEL TOALHA. A sub-lista de suplementos/vitaminas
# (hpc/3764441) traz produtos de saude de verdade. Aqui trocamos SO a URL
# (o rotulo e a chave continuam "hpc" -> "Saude").
MARKET_CATEGORY_PATH = {
    ("US", "hpc"): "hpc/3764441",
}

def _stable_asin(real_asin):
    # Gera um codigo estavel (sempre o mesmo para o mesmo produto) a partir
    # do ASIN real. Assim o mesmo produto nao gera video novo em cada busca,
    # ao mesmo tempo que mantem o ASIN real mascarado.
    digest = hashlib.sha1(real_asin.encode("utf-8")).hexdigest().upper()
    return "M" + digest[:9]


def _to_int_count(text):
    # "12,345" (US) ou "12.345" (BR) -> 12345. Ignora tudo que nao e digito.
    digits = re.sub(r"\D", "", text or "")
    if not digits:
        return None
    try:
        value = int(digits)
    except ValueError:
        return None
    return value if value > 0 else None


def _to_float_rating(text):
    # "4.6" ou "4,6" -> 4.6. So aceita nota plausivel de 0 a 5.
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 0.0 <= value <= 5.0 else None


def _extract_rating_and_reviews(block):
    # Le as estrelas (rating) e o numero de avaliacoes (review_count) do bloco
    # de um produto na pagina "Mais Vendidos". Retorna (rating, review_count),
    # cada um podendo ser None se a pagina nao trouxer.
    rating = None
    reviews = None

    # 1) aria-label costuma trazer os DOIS de uma vez:
    #    "4.6 out of 5 stars, 12,345 ratings" / "4,6 de 5 estrelas, 12.345 avaliacoes"
    aria = re.search(
        r'aria-label="([^"]*?(?:out of 5|de 5)[^"]*)"',
        block,
        re.IGNORECASE,
    )
    if aria:
        text = aria.group(1)
        star_in_aria = re.search(r"(\d+[.,]\d+)", text)
        if star_in_aria:
            rating = _to_float_rating(star_in_aria.group(1))
        after = re.search(r"(?:stars?|estrelas?)\s*,?\s*([\d.,]+)", text, re.IGNORECASE)
        if after:
            reviews = _to_int_count(after.group(1))

    # 2) Fallback do rating: texto "4.6 out of 5" / "4,6 de 5" em qualquer lugar.
    if rating is None:
        star = re.search(r"(\d+[.,]\d+)\s*(?:out of 5|de 5)", block, re.IGNORECASE)
        if star:
            rating = _to_float_rating(star.group(1))

    # 3) Fallback do numero de avaliacoes: "12,345 ratings" / "12.345 avaliacoes".
    if reviews is None:
        cnt = re.search(
            r'([\d.,]{1,})\s*(?:ratings?|reviews?|avalia\w+)',
            block,
            re.IGNORECASE,
        )
        if cnt:
            reviews = _to_int_count(cnt.group(1))

    return rating, reviews

def _get_html(url, headers, tries=3):
    # A Amazon as vezes responde 503 (bloqueio temporario). Tenta de novo.
    last = ""
    for attempt in range(tries):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            last = res.text
            if res.status_code == 200:
                return res.text
        except Exception:
            pass
        time.sleep(2 + attempt)  # espera crescente entre as tentativas
    return last

def fetch_category(domain, market, category, tag, limit):
    # "Mais Vendidos" da categoria (ranking do mais vendido -> menos vendido).
    path = MARKET_CATEGORY_PATH.get((market, category), category)
    url = f"https://www.{domain}/gp/bestsellers/{path}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8"
    }
    label = CATEGORIES.get(category, category)
    products = []
    seen = set()
    print(f"Buscando MAIS VENDIDOS [{market}] - {label}...")
    try:
        html = _get_html(url, headers)
        # Divide a pagina em blocos de produto. Cada produto comeca em
        # id="gridItemRoot"; pegamos um trecho generoso de cada.
        chunks = html.split('id="gridItemRoot"')[1:]

        for chunk in chunks:
            block = chunk[:3000]
            # ASIN: usa atributos ESTAVEIS (nao dependem de classes ofuscadas,
            # que mudam entre amazon.com e amazon.com.br).
            asin_match = (
                re.search(r'data-asin="([A-Z0-9]{10})"', block)
                or re.search(r'/dp/([A-Z0-9]{10})', block)
                or re.search(r'dp/([A-Z0-9]{10})', block)
            )
            # Titulo: o texto "alt" da imagem do produto e o proprio nome.
            title_match = re.search(r'<img[^>]*\balt="([^"]{4,})"', block)
            img_match = re.search(r'<img[^>]*\bsrc="(https://[^"]+)"', block)
            # Preco (opcional): a-offscreen guarda o preco formatado.
            price_match = re.search(r'a-offscreen">([^<]+)</span>', block)

            # Estrelas + numero de avaliacoes = sinal REAL de "mais vendido".
            # Comparavel entre categorias: quem tem mais avaliacoes vendeu mais.
            # A pagina traz num aria-label tipo:
            #   "4.6 out of 5 stars, 12,345 ratings"  (US)
            #   "4,6 de 5 estrelas, 12.345 avaliacoes" (BR)
            rating_val, reviews_val = _extract_rating_and_reviews(block)

            if asin_match and title_match and img_match:
                real_asin = asin_match.group(1)
                if real_asin in seen:
                    continue
                seen.add(real_asin)
                fake_asin = _stable_asin(real_asin)  # Mascara o ASIN, mas de forma estavel
                title = title_match.group(1).replace("&quot;", '"').replace("&amp;", "&").strip()
                products.append({
                    "asin": fake_asin,
                    "marketplace_code": market,
                    "title": title,
                    "price_display": price_match.group(1).strip() if price_match else "Site",
                    "image_url": img_match.group(1),
                    "affiliate_url": f"https://www.{domain}/dp/{real_asin}?tag={tag}",
                    "category": category,
                    "category_label": label,
                    "rating": rating_val,
                    "review_count": reviews_val,
                    "source": f"bestsellers_{category}"
                })
            if len(products) >= limit:
                break  # Pega os TOP mais vendidos (ordem: mais vendido -> menos vendido)
    except Exception:
        print(f"Erro ao buscar [{market}] - {label}: pulando...")
    time.sleep(1)  # Previne bloqueio instantaneo do servidor
    return products

def _selected_categories():
    # Permite escolher as categorias por variavel de ambiente.
    raw = os.getenv("ATLAS_SCRAPER_CATEGORIES", "").strip()
    if raw:
        chosen = [c.strip() for c in raw.split(",") if c.strip()]
        return [c for c in chosen if c in CATEGORIES] or list(CATEGORIES.keys())
    # Padrao: TODAS as categorias. O painel mostra todas, na ordem dos mais
    # vendidos. (Cada categoria e UMA unica requisicao, entao cobrir todas
    # nao deixa a busca muito mais lenta.)
    return list(CATEGORIES.keys())

def main():
    # Grava no mesmo lugar em que o pipeline LE os produtos (ATLAS_ROOT/storage).
    # Antes estava fixo em "/atlas/..." e nao funcionava no Windows.
    root = Path(os.getenv("ATLAS_ROOT", "")).resolve() if os.getenv("ATLAS_ROOT") else Path.cwd().resolve()
    if not (root / "app").exists():
        root = Path.cwd().resolve()
    imports_dir = root / "storage" / "amazon" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    out_path = imports_dir / "bestsellers_OMNI.json"

    categories = _selected_categories()

    # Quantos produtos coletar por categoria/mercado (so metadados, rapido).
    # E' a mesma pagina, entao pegar mais itens nao custa requisicoes extras.
    try:
        limit = int(os.getenv("ATLAS_SCRAPER_LIMIT_PER_CATEGORY", "10"))
    except Exception:
        limit = 10
    limit = max(1, limit)

    all_products = []
    # Categorias que voltaram COM produtos nesta busca (market, slug).
    fetched_keys = set()

    def _collect(domain, market, tag):
        for cat in categories:
            prods = fetch_category(domain, market, cat, tag, limit)
            if prods:
                fetched_keys.add((market, cat))
                all_products.extend(prods)

    # BRASIL e EUA - Mais Vendidos por categoria
    _collect("amazon.com.br", "BR", "achadosatlasb-20")
    _collect("amazon.com", "US", "atlasfindsus-20")

    # IMPORTANTE: nao apagar o que ja tinhamos. Se a rede bloqueou uma
    # categoria agora (voltou vazia), mantemos os produtos anteriores dela.
    # Assim uma busca bloqueada nunca "encolhe" a lista do painel.
    existing = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    merged = list(all_products)
    kept = 0
    for item in existing:
        key = (item.get("marketplace_code"), str(item.get("category") or "").lower())
        if key not in fetched_keys:
            merged.append(item)
            kept += 1

    # Salva o arquivo
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(
        f"SUCESSO: {len(all_products)} produtos novos + {kept} mantidos "
        f"= {len(merged)} no total (MAIS VENDIDOS por categoria)."
    )

if __name__ == "__main__":
    main()
