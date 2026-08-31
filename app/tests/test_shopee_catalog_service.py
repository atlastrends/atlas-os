import pytest

from app.services import shopee_catalog_service as service


CSV = """product_id;title;category;price;affiliate_url;image_url;video_url;commission_rate;commission_amount;sold_count
123;Fone Bluetooth;Eletronicos;R$ 99,90;https://shopee.com.br/product/1/123;https://cf.shopee.com.br/file/image.jpg;https://cf.shopee.com.br/file/video.mp4;12,5;12,49;2500
"""


def test_parse_csv_ranks_and_validates_product():
    products = service.parse_csv(CSV.encode("utf-8"), rights_confirmed=True)

    assert len(products) == 1
    assert products[0].product_id == "123"
    assert products[0].commission_rate == 12.5
    assert products[0].sold_count == 2500
    assert products[0].ready_for_video is True
    assert products[0].score > 0


def test_parse_csv_requires_media_rights_confirmation():
    with pytest.raises(service.ShopeeCatalogError, match="autorizacao"):
        service.parse_csv(CSV.encode("utf-8"), rights_confirmed=False)


def test_parse_csv_rejects_non_shopee_affiliate_url():
    invalid = CSV.replace(
        "https://shopee.com.br/product/1/123",
        "https://example.com/product/123",
    )

    with pytest.raises(service.ShopeeCatalogError, match="shopee.com.br"):
        service.parse_csv(invalid.encode("utf-8"), rights_confirmed=True)


def test_parse_csv_rejects_third_party_video():
    invalid = CSV.replace(
        "https://cf.shopee.com.br/file/video.mp4",
        "https://www.tiktok.com/video/123",
    )

    with pytest.raises(service.ShopeeCatalogError, match="midia oficial"):
        service.parse_csv(invalid.encode("utf-8"), rights_confirmed=True)


def test_materialize_pipeline_import_creates_both_languages(monkeypatch, tmp_path):
    products = service.parse_csv(CSV.encode("utf-8"), rights_confirmed=True)
    output = tmp_path / "imports" / "catalog.json"
    monkeypatch.setattr(service, "PIPELINE_IMPORT_PATH", output)

    service.materialize_pipeline_import(products)

    data = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert {item["language"] for item in data} == {"pt-BR", "en-US"}
    assert all(item["platform"] == "shopee" for item in data)
    assert all(item["media_rights_confirmed"] is True for item in data)
