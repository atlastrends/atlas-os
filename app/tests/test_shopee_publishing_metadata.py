from types import SimpleNamespace

from app.services.publishing_service import PublishingService
from app.models.dashboard import VideoStatusEnum


def _asset():
    return SimpleNamespace(
        payload={
            "title": (
                "Mais Recente Airs Pro Fones De Ouvido Sem Fio Bluetooth "
                "Super Bass Headset Com Cancelamento De Ruido ANC"
            ),
            "platform": "shopee",
            "marketplace_code": "BR",
            "category_label": "Audio e Fones de Ouvido",
            "brand": "",
        },
        title="airs-pro",
        country_code="BR",
        language="pt-BR",
    )


def test_shopee_hashtags_are_product_specific_and_not_amazon():
    service = PublishingService.__new__(PublishingService)

    _caption, _description, tags = service._affiliate_caption(
        _asset(),
        "instagram",
    )

    assert "#airspro" in tags
    assert "#fonesbluetooth" in tags
    assert "#fonessemfio" in tags
    assert "#superbass" in tags
    assert "#cancelamentoderuido" in tags
    assert "#anc" in tags
    assert "#achadosshopee" in tags
    assert "#shopee" in tags
    assert "#achadinhos" in tags
    assert "#achadosdaamazon" not in tags
    assert "#amazonbrasil" not in tags


def test_shopee_hashtag_limits_follow_social_platform():
    service = PublishingService.__new__(PublishingService)

    _caption, _description, tiktok_tags = service._affiliate_caption(
        _asset(),
        "tiktok",
    )
    _caption, _description, youtube_tags = service._affiliate_caption(
        _asset(),
        "youtube",
    )

    assert len(tiktok_tags) <= 6
    assert len(youtube_tags) <= 10
    assert tiktok_tags[:3] == [
        "#airspro",
        "#fonesbluetooth",
        "#fonessemfio",
    ]
    assert "#achadosshopee" in tiktok_tags
    assert "#shopee" in tiktok_tags
    assert "#achadinhos" in tiktok_tags


def test_shopee_asset_never_publishes_to_social_platforms():
    class Database:
        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    database = Database()
    service = PublishingService.__new__(PublishingService)
    service.db = database
    asset = SimpleNamespace(
        id=42,
        payload={"platform": "shopee"},
        status=VideoStatusEnum.CREATED,
        review_notes=None,
        reviewed_at=None,
    )

    result = service.approve_and_publish(
        asset,
        platforms=["instagram", "tiktok", "youtube", "facebook"],
    )

    assert result["held"] is True
    assert result["publications"] == []
    assert asset.status == VideoStatusEnum.APPROVED
    assert "outras plataformas bloqueada" in asset.review_notes
    assert database.commits == 1
