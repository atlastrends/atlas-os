import json

from app.automation import authorized_broll_renderer as renderer
from app.automation.real_amazon_pipeline import Product


def _product() -> Product:
    return Product(
        marketplace_code="BR",
        asin="S123456789",
        title="Fones Bluetooth Airs Pro",
        price_display="R$ 67,90",
        image_url="https://down-br.img.susercontent.com/file/image",
        detail_url="https://shopee.com.br/product/1/2",
        source="test",
        platform="shopee",
        features=["Controle por toque"],
    )


def test_shopee_uses_same_llm_sequence_as_amazon(monkeypatch):
    calls = []
    response = json.dumps(
        {
            "scenes": [
                {"caption": f"cena {index}", "voice": f"fala {index}"}
                for index in range(1, 6)
            ]
        }
    )

    def groq(_prompt):
        calls.append("groq")
        return response

    def gemini(_prompt):
        calls.append("gemini")
        return None

    monkeypatch.setattr(renderer, "_groq_story_text", groq)
    monkeypatch.setattr(renderer, "_gemini_story_text", gemini)

    story = renderer._llm_story(_product(), "BR", "reel")

    assert len(story) == 5
    assert calls == ["groq"]


def test_shopee_external_video_requires_exact_short_hd_candidate(
    monkeypatch,
    tmp_path,
):
    candidates = [
        {
            "id": "long",
            "title": "Airs Pro product video",
            "channel": "Shopee Oficial",
            "duration": 61,
            "height": 1080,
        },
        {
            "id": "low",
            "title": "Airs Pro product video",
            "channel": "Shopee Oficial",
            "duration": 30,
            "height": 480,
        },
        {
            "id": "valid",
            "title": "Airs Pro product video",
            "channel": "Shopee Oficial",
            "duration": 45,
            "height": 1080,
        },
    ]
    downloaded = []
    monkeypatch.setattr(renderer, "approved_terms", lambda: [])
    monkeypatch.setattr(
        renderer,
        "choose_candidates",
        lambda _product: candidates,
    )

    def download(candidate, _work):
        downloaded.append(candidate["id"])
        return {
            "path": tmp_path / "video.mp4",
            "source_url": "https://example.com/video",
            "channel": candidate["channel"],
            "license_status": "",
        }

    monkeypatch.setattr(renderer, "download_broll", download)

    result = renderer._authorized_exact_video(_product(), tmp_path)

    assert downloaded == ["valid"]
    assert result["license_status"] == "official_or_approved_channel"


def test_shopee_falls_back_to_images_after_video_sources(monkeypatch, tmp_path):
    calls = []
    product = _product()
    product.listing_image_urls = [
        "https://down-br.img.susercontent.com/file/image"
    ]
    monkeypatch.setattr(renderer, "_fetch_listing_html", lambda _url: "")
    monkeypatch.setattr(
        renderer,
        "_official_page_video",
        lambda *_args: calls.append("official") or None,
    )
    monkeypatch.setattr(
        renderer,
        "_authorized_exact_video",
        lambda *_args: calls.append("external") or None,
    )

    def image(_url, destination):
        calls.append("image")
        destination.write_bytes(b"image")
        return True

    monkeypatch.setattr(renderer, "_download_listing_image", image)

    video, images, _metadata = renderer.fetch_listing_media(product, tmp_path)

    assert video is None
    assert len(images) == 1
    assert calls == ["official", "external", "image"]


def test_affiliate_video_fails_closed_when_visual_product_differs(
    monkeypatch,
    tmp_path,
):
    from app.services import trend_relevance_service

    video = tmp_path / "wrong.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        trend_relevance_service,
        "passes_gate",
        lambda *_args, **_kwargs: (
            False,
            {
                "evaluated": True,
                "confidence": 99,
                "reason": "mostra outro produto",
            },
        ),
    )

    assert renderer._affiliate_video_matches_product(
        _product(),
        video,
    ) is False


def test_affiliate_video_fails_closed_when_vision_is_unavailable(
    monkeypatch,
    tmp_path,
):
    from app.services import trend_relevance_service

    video = tmp_path / "unknown.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        trend_relevance_service,
        "passes_gate",
        lambda *_args, **_kwargs: (
            True,
            {
                "evaluated": False,
                "confidence": 0,
                "reason": "juiz indisponivel",
            },
        ),
    )

    assert renderer._affiliate_video_matches_product(
        _product(),
        video,
    ) is False


def test_amazon_ignores_unrelated_generic_sponsored_video():
    html = """
    <a href="https://www.amazon.com/dp/OTHERASIN1">
      <video src="https://m.media-amazon.com/sponsored.mp4"></video>
    </a>
    """

    assert renderer._extract_listing_video_url(
        html,
        platform="amazon",
    ) is None


def test_amazon_extracts_structured_product_gallery_video():
    html = """
    "videos":[{
      "isVideo":true,
      "title":"Exact Product",
      "url":"https://m.media-amazon.com/product-video.mp4"
    }],
    "mediaAsin":"B012345678"
    """

    assert renderer._extract_listing_video_url(
        html,
        platform="amazon",
        expected_asin="B012345678",
    ) == "https://m.media-amazon.com/product-video.mp4"


def test_amazon_structured_video_survives_unavailable_vision(
    monkeypatch,
    tmp_path,
):
    from app.services import trend_relevance_service

    product = _product()
    product.platform = "amazon"
    video = tmp_path / "structured.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        trend_relevance_service,
        "passes_gate",
        lambda *_args, **_kwargs: (
            False,
            {
                "evaluated": False,
                "confidence": 0,
                "reason": "quota",
            },
        ),
    )

    assert renderer._affiliate_video_matches_product(
        product,
        video,
        structurally_verified=True,
    ) is True
