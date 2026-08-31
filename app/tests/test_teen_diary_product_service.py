from app.services.teen_diary_product_service import TeenDiaryProductService


def test_select_pair_uses_same_safe_prop_family_and_valid_affiliate_links():
    service = TeenDiaryProductService()

    pair = service.select_pair("escola", "day-1-part-1")

    assert pair
    assert pair["br"]["prop_type"] == pair["us"]["prop_type"]
    assert pair["br"]["url"].startswith("https://www.amazon.com.br/dp/")
    assert "tag=" in pair["br"]["url"]
    assert pair["us"]["url"].startswith("https://www.amazon.com/dp/")
    assert "tag=" in pair["us"]["url"]


def test_localized_caption_is_transparent_and_parent_directed():
    service = TeenDiaryProductService()
    pair = service.select_pair("escola", "day-1-part-1")

    pt = service.localized_caption(pair, "pt")
    en = service.localized_caption(pair, "en")

    assert "Link de afiliado" in pt
    assert "adulto responsável" in pt
    assert "Affiliate link" in en
    assert "parent or guardian" in en
    assert "compre agora" not in pt.lower()
    assert "buy now" not in en.lower()
