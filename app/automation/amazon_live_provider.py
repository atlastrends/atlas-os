from typing import Any
import logging
import requests
import random
import time
import re
import html

from app.automation.real_amazon_pipeline import Product, MARKETS, log_event

logger = logging.getLogger(__name__)

class AmazonNativeScraperProvider:
    """Busca produtos reias raspando paginas Amazon sem dependencias externas"""

    def __init__(self):
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
        ]

    def extract_field(self, pattern: str, text: str) -> str:
        match = re.search(pattern, text)
        if match:
            return html.unescape(match.group(1).strip())
        return ""

    def discover_live(self) -> list[Product]:
        products: list[Product] = []

        searches = {
            "BR": "https://www.amazon.com.br/s?k=eletronicos+mais+vendidos",
            "US": "https://www.amazon.com/s?k=bestseller+electronics"
        }

        for market_code, search_url in searches.items():
            log_event("AMAZON_NATIVE_SCRAPER_START", market=market_code, url=search_url)
            config = MARKETS[market_code]

            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7" if market_code == "BR" else "en-US,en;q=0.9",
                "Referer": f"https://www.{config['domain']}/"
            }

            try:
                response = requests.get(search_url, headers=headers, timeout=15)
                
                if response.status_code != 200:
                    log_event("AMAZON_NATIVE_SCRAPER_BLOCKED", market=market_code, status=response.status_code)
                    continue

                html_text = response.text
                
                # Encontrar blocos de produtos individuais (data-asin)
                blocks = re.findall(r'<div[^>]*data-asin="([^"]+)"[^>]*>(.*?)<div[^>]*data-asin=', html_text, re.DOTALL | re.IGNORECASE)
                
                # Fallback caso a regex de bloco falhe, extrair no escopo geral da pagina
                if not blocks:
                     # Dividindo grosseiramente por marcadores de ASIN
                     parts = html_text.split('data-asin="')
                     blocks = []
                     for p in parts[1:]:
                         asin_match = p.split('"')[0]
                         if len(asin_match) == 10 and asin_match.isalnum():
                             blocks.append((asin_match, p))

                added_count = 0
                for asin, block_html in blocks:
                    if added_count >= 5:
                        break

                    asin = asin.strip()
                    if not asin or len(asin) != 10:
                        continue

                    # Extrair Imagem
                    image_url = self.extract_field(r'<img[^>]*class="s-image"[^>]*src="([^"]+)"', block_html)
                    
                    # Extrair Titulo
                    title = self.extract_field(r'<span[^>]*class="a-size-[a-z]+ a-color-base a-text-normal"[^>]*>([^<]+)</span>', block_html)
                    if not title:
                         title = self.extract_field(r'<img[^>]*class="s-image"[^>]*alt="([^"]+)"', block_html)

                    if not title or not image_url or "Patrocinado" in title or "Sponsored" in title:
                        continue

                    # Extrair Preço
                    price_display = self.extract_field(r'<span class="a-offscreen">([^<]+)</span>', block_html)
                    
                    # Extrair Avaliação
                    rating_text = self.extract_field(r'<span class="a-icon-alt">([^<]+)</span>', block_html)
                    rating = 0.0
                    try:
                        if rating_text:
                            # 4,5 de 5 estrelas ou 4.5 out of 5
                            num_str = rating_text.split(" ")[0].replace(",", ".")
                            rating = float(num_str)
                    except:
                        pass

                    detail_url = f"https://www.{config['domain']}/dp/{asin}?tag={config['partner_tag']}"

                    product = Product(
                        asin=asin,
                        marketplace_code=market_code,
                        title=title[:250],
                        image_url=image_url,
                        detail_url=detail_url,
                        source="native_scraper",
                        price_display=price_display,
                        price_amount=0.0,
                        currency=config["currency"],
                        rating=rating,
                        features=[
                            "Produto em destaque na Amazon" if market_code == "BR" else "Amazon Highlight",
                            "Alta procura nesta categoria" if market_code == "BR" else "Trending in this category"
                        ],
                        search_position=added_count + 1
                    )
                    
                    products.append(product)
                    added_count += 1

                log_event("AMAZON_NATIVE_SCRAPER_SUCCESS", market=market_code, products_found=added_count)
                time.sleep(2)

            except Exception as e:
                log_event("AMAZON_NATIVE_SCRAPER_FAILED", market=market_code, error=str(e))

        return products

def inject_provider():
    import app.automation.real_amazon_pipeline as rap
    original_discover = rap.discover_products

    def new_discover_products() -> list[Product]:
        provider = AmazonNativeScraperProvider()
        live_products = provider.discover_live()
        
        if live_products:
            log_event("PRODUCT_DISCOVERY_COMPLETED", source="native_scraper", count=len(live_products))
            return rap.deduplicate(live_products)
        else:
             return original_discover()

    rap.discover_products = new_discover_products

inject_provider()