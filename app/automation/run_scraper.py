import json
import os
import hashlib
import html as html_lib
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
    # Categorias adicionais (testadas e confirmadas com produtos reais em
    # BR e US, mesmo slug funciona nos dois mercados) para garantir pelo
    # menos 15 categorias disponiveis em cada mercado.
    "automotive": "Automotivo",
    "fashion": "Moda",
    "books": "Livros",
    "grocery": "Mercado",
    "musical-instruments": "Instrumentos Musicais",
    "appliances": "Eletrodomesticos",
}

# Em alguns mercados a lista geral da categoria nao faz jus ao nome, ou o slug
# padrao simplesmente nao traz produtos (pagina vazia). Aqui trocamos SO a URL
# usada na busca (o rotulo e a chave do painel continuam os mesmos).
# - US "hpc": "Health & Household" e' dominada por PILHAS/PAPEL TOALHA; a
#   sub-lista de suplementos/vitaminas (hpc/3764441) traz produtos de saude.
# - US "home"/"sports": o slug simples nao retorna produtos no site dos EUA;
#   "home-garden"/"sporting-goods" sao os slugs que realmente funcionam la.
# - BR "pet-supplies"/"office-products": os slugs padrao (iguais ao US) dao
#   erro 503 ou pagina vazia no site brasileiro; "pet-products"/"office" sao
#   os slugs que realmente trazem produtos por la.
MARKET_CATEGORY_PATH = {
    ("US", "hpc"): "hpc/3764441",
    ("US", "home"): "home-garden",
    ("US", "sports"): "sporting-goods",
    ("BR", "pet-supplies"): "pet-products",
    ("BR", "office-products"): "office",
}

def _stable_asin(real_asin):
    # Gera um codigo estavel (sempre o mesmo para o mesmo produto) a partir
    # do ASIN real. Assim o mesmo produto nao gera video novo em cada busca,
    # ao mesmo tempo que mantem o ASIN real mascarado.
    digest = hashlib.sha1(real_asin.upper().encode("utf-8")).hexdigest().upper()
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

def _subcats_enabled():
    # Ligado por padrao: quando os "mais vendidos" do topo de cada categoria
    # se esgotam (viram video), o robo desce nas SUBCATEGORIAS de cada
    # categoria (tambem em ordem de mais vendido -> menos vendido), o que
    # multiplica o numero de produtos disponiveis. Desligavel com
    # ATLAS_SCRAPER_SUBCATEGORIES=0.
    return (os.getenv("ATLAS_SCRAPER_SUBCATEGORIES", "1").strip().lower()
            not in {"0", "false", "no", "off"})


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _max_subcats():
    return max(0, _env_int("ATLAS_SCRAPER_MAX_SUBCATS", 12))


def _sub_limit(default_limit):
    return max(1, _env_int("ATLAS_SCRAPER_LIMIT_PER_SUBCATEGORY", default_limit))


def _max_depth():
    # Profundidade da arvore: 0 = so o topo do departamento, 1 = departamento
    # + subcategorias diretas, 2 = + sub-subcategorias, e assim por diante.
    return max(0, _env_int("ATLAS_SCRAPER_MAX_DEPTH", 1))


def _max_departments():
    # 0 = TODOS os departamentos que a Amazon oferece.
    return max(0, _env_int("ATLAS_SCRAPER_MAX_DEPARTMENTS", 0))


def _request_budget():
    # Teto de paginas por mercado, para a busca completa nao ficar infinita.
    return max(1, _env_int("ATLAS_SCRAPER_MAX_REQUESTS", 2000))


def _headers(market):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8" if market == "BR" else "en-US,en;q=0.9",
    }


def _clean_name(text):
    return html_lib.unescape(str(text or "")).strip()


# Departamentos do topo (nivel 0) na pagina raiz de "Mais Vendidos".
#   BR: /gp/bestsellers/<slug>/ref=zg_bs_nav_<slug>_0
#   US: /Best-Sellers-.../zgbs/<slug>/ref=zg_bs_nav_<slug>_0
_DEPT_RE = re.compile(
    r'<a[^>]+href="/[^"]*?(?:zgbs|gp/bestsellers)/([a-zA-Z0-9-]+)/ref=zg_bs_nav_'
    r'[a-zA-Z0-9-]+_0[^"]*"[^>]*>\s*([^<]{2,70}?)\s*</a>'
)

# Links de SUBCATEGORIA (tem nodeId) e o nivel deles:
#   .../<slug>/<nodeId>/ref=zg_bs_nav_<x>_<level>
_NAV_RE = re.compile(
    r'<a[^>]+href="(/[^"]*?(?:zgbs|gp/bestsellers)/[a-zA-Z0-9-]+/\d+/ref=zg_bs_nav_'
    r'[a-zA-Z0-9-]+_(\d+)[^"]*)"[^>]*>\s*([^<]{2,70}?)\s*</a>'
)


def discover_departments(domain, headers):
    """Descobre TODOS os departamentos de 'Mais Vendidos' na raiz do site.

    Retorna [(slug, nome, url)] na ordem em que a Amazon os lista (aprox. dos
    mais relevantes para os menos)."""
    root = f"https://www.{domain}/gp/bestsellers/"
    page = ""
    for _ in range(4):
        page = _get_html(root, headers)
        if page and _DEPT_RE.search(page):
            break
        time.sleep(3)
    out = []
    seen = set()
    for slug, name in _DEPT_RE.findall(page):
        if slug in seen:
            continue
        seen.add(slug)
        out.append((slug, _clean_name(name), f"https://www.{domain}/gp/bestsellers/{slug}/"))
    return out


def _child_nodes(page, domain, level):
    """Extrai os links de subcategoria de UM nivel especifico a partir do HTML
    ja baixado. Retorna [(url, nome)] na ordem da pagina (mais -> menos)."""
    out = []
    seen = set()
    for href, lvl, name in _NAV_RE.findall(page or ""):
        if int(lvl) != level:
            continue
        key = href.split("/ref=")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((f"https://www.{domain}{href}", _clean_name(name)))
    return out


def _get_page(url, headers, tries=4, min_len=80000):
    """Baixa a pagina garantindo a versao COMPLETA. A Amazon as vezes responde
    200 com uma variante enxuta (tem produtos, mas sem a arvore de navegacao),
    o que faz o crawler nao achar as subcategorias. Retenta ate vir a pagina
    cheia (ou esgotar as tentativas)."""
    page = ""
    for _ in range(tries):
        page = _get_html(url, headers)
        if page and len(page) >= min_len:
            return page
        time.sleep(2)
    return page


def crawl_department(domain, market, tag, slug, label, dept_url, headers,
                     top_limit, sub_limit, max_depth, max_subcats, budget):
    """Percorre um departamento e suas subcategorias (mais vendido -> menos),
    ate a profundidade configurada. Retorna os produtos (dedup por ASIN), todos
    marcados com o departamento (slug/label) para agrupar no painel."""
    products = []
    seen_asins = set()

    def _add(items):
        for item in items:
            asin = item.get("asin")
            if asin and asin not in seen_asins:
                seen_asins.add(asin)
                products.append(item)

    # Fila (nivel a nivel): (url, level, source).
    queue = [(dept_url, 0, f"bestsellers_{slug}")]
    visited = set()
    while queue:
        if budget["n"] <= 0:
            break
        url, level, source = queue.pop(0)
        node_key = url.split("/ref=")[0]
        if node_key in visited:
            continue
        visited.add(node_key)
        budget["n"] -= 1

        # Nos que ainda vao descer precisam da pagina COMPLETA (com a arvore de
        # navegacao). Folhas (ultimo nivel) so precisam dos produtos, entao usam
        # o fetch rapido - isso acelera MUITO a busca completa.
        need_children = level < max_depth
        page = _get_page(url, headers) if need_children else _get_html(url, headers)
        limit = top_limit if level == 0 else sub_limit
        _add(_extract_products_from_html(
            page, market, domain, slug, label, tag, limit, source=source
        ))
        time.sleep(1)  # Previne bloqueio instantaneo do servidor

        if need_children:
            for child_url, _child_name in _child_nodes(page, domain, level + 1)[:max_subcats]:
                queue.append((child_url, level + 1, f"bestsellers_{slug}_sub"))
    return products


def _parse_bestsellers_html(url, headers, market, domain, category, label, tag, limit, source=None):
    """Baixa a pagina e extrai os produtos (mantido por compatibilidade)."""
    html = _get_html(url, headers)
    products = _extract_products_from_html(
        html, market, domain, category, label, tag, limit, source=source
    )
    if not products:
        print(f"Erro ou pagina vazia [{market}] - {label}: pulando...")
    time.sleep(1)  # Previne bloqueio instantaneo do servidor
    return products


def _extract_products_from_html(html, market, domain, category, label, tag, limit, source=None):
    products = []
    seen = set()
    try:
        # Divide a pagina em blocos de produto. Cada produto comeca em
        # id="gridItemRoot"; pegamos um trecho generoso de cada.
        chunks = (html or "").split('id="gridItemRoot"')[1:]

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
                    "source": source or f"bestsellers_{category}"
                })
            if len(products) >= limit:
                break  # Pega os TOP mais vendidos (ordem: mais vendido -> menos vendido)
    except Exception:
        print(f"Erro ao extrair produtos [{market}] - {label}: pulando...")
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

def _persist(out_path, labels_path, all_products, fetched_keys, discovered_labels):
    """Salva o pool (merge com o existente, sem encolher categorias nao buscadas
    nesta rodada) e os rotulos de categoria. Chamado incrementalmente para que o
    progresso nunca se perca e o painel atualize ao vivo."""
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
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    tmp.replace(out_path)

    labels = {}
    if labels_path.exists():
        try:
            labels = json.loads(labels_path.read_text(encoding="utf-8"))
        except Exception:
            labels = {}
    labels.update(discovered_labels)
    with open(labels_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)
    return len(merged), kept


def main():
    # Grava no mesmo lugar em que o pipeline LE os produtos (ATLAS_ROOT/storage).
    default_root = Path(__file__).resolve().parents[2]
    root = Path(os.getenv("ATLAS_ROOT") or default_root).resolve()
    if not (root / "app").exists():
        root = default_root
    imports_dir = root / "storage" / "amazon" / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    out_path = imports_dir / "bestsellers_OMNI.json"
    labels_path = imports_dir / "category_labels.json"

    top_limit = max(1, _env_int("ATLAS_SCRAPER_LIMIT_PER_CATEGORY", 15))
    sub_limit = _sub_limit(top_limit)
    max_depth = _max_depth() if _subcats_enabled() else 0
    max_subcats = _max_subcats()
    max_departments = _max_departments()

    all_products = []
    fetched_keys = set()          # (market, slug) com produtos nesta rodada
    discovered_labels = {}        # slug -> rotulo (inclui categorias NOVAS)

    markets = [
        ("amazon.com", "US", "atlasfindsus-20"),
        ("amazon.com.br", "BR", "achadosatlasb-20"),
    ]
    for domain, market, tag in markets:
        headers = _headers(market)
        budget = {"n": _request_budget()}
        departments = discover_departments(domain, headers)
        if not departments:
            print(f"[{market}] nenhum departamento descoberto (bloqueio?). Pulando.")
            continue
        if max_departments > 0:
            departments = departments[:max_departments]
        print(f"[{market}] {len(departments)} departamentos descobertos (TODOS os da Amazon).")

        for slug, name, dept_url in departments:
            # Rotulo: mantem o nome PT curado quando conhecido; senao usa o
            # nome que a Amazon deu (CRIA a categoria nova automaticamente).
            label = (CATEGORIES.get(slug)
                     or name or slug.replace("-", " ").title())
            discovered_labels[slug] = label
            print(f"  [{market}] {label} ...", flush=True)
            prods = crawl_department(
                domain, market, tag, slug, label, dept_url, headers,
                top_limit, sub_limit, max_depth, max_subcats, budget,
            )
            if prods:
                fetched_keys.add((market, slug))
                all_products.extend(prods)
            # Salva a cada departamento: progresso nunca se perde.
            total, kept = _persist(
                out_path, labels_path, all_products, fetched_keys, discovered_labels
            )
            print(f"     -> {len(prods)} produtos | pool {total} | orcamento {budget['n']}.")
            if budget["n"] <= 0:
                print(f"  [{market}] orcamento de requisicoes esgotado; parando cedo.")
                break

    total, kept = _persist(
        out_path, labels_path, all_products, fetched_keys, discovered_labels
    )
    print(
        f"SUCESSO: {len(all_products)} produtos novos + {kept} mantidos "
        f"= {total} no total | {len(discovered_labels)} categorias "
        f"(TODAS as que a Amazon oferece, mais vendido -> menos vendido)."
    )

if __name__ == "__main__":
    main()
