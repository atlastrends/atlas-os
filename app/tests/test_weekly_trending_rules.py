import pytest

from app.services.content_service import ContentService
from app.services.media_service import (
    MediaService,
    NoFaithfulVoiceError,
)
from app.services.metadata_service import MetadataService
from app.services.trend_service import TrendService
from app.workers.loop_worker import Engine


def _trend(topic, views, description="Descrição real suficientemente completa."):
    return {
        "topic": topic,
        "score": 0,
        "views": views,
        "source": "YouTube MostPopular / Canal",
        "geo": "BR",
        "category": "popular",
        "hashtags": [],
        "published_at": "2026-08-30T00:00:00Z",
        "description": description,
        "video_id": topic,
    }


def test_default_trending_window_is_seven_days(monkeypatch):
    monkeypatch.delenv("ATLAS_TREND_MAX_AGE_HOURS", raising=False)

    service = TrendService()

    assert service.max_age_hours == 168


def test_trends_are_ranked_only_by_real_views(monkeypatch):
    service = TrendService()
    monkeypatch.setattr(
        service,
        "_fetch_youtube_most_popular",
        lambda _geo: [
            _trend("Segundo vídeo específico", 2_000),
            _trend("Primeiro vídeo específico", 9_000),
        ],
    )
    monkeypatch.setattr(
        service,
        "_fetch_youtube_categories",
        lambda _geo: [
            _trend("Terceiro vídeo específico", 500),
            _trend("Sem visualizações reais", 0),
        ],
    )

    trends = service.fetch_trends("BR")

    assert [trend["views"] for trend in trends] == [9_000, 2_000, 500]
    assert all(trend["views"] > 0 for trend in trends)


def test_worker_preserves_weekly_view_order_without_score(monkeypatch):
    engine = Engine.__new__(Engine)
    monkeypatch.setattr(
        engine,
        "_was_topic_used_recently",
        lambda *_args: False,
    )
    trends = [
        _trend("Vídeo semanal mais visto", 50_000),
        _trend("Vídeo semanal segundo lugar", 40_000),
        _trend("Vídeo semanal terceiro lugar", 30_000),
    ]

    selected = engine._select_best_unique_trends(
        trends,
        target_videos=1,
        country_code="BR",
        pool_size=len(trends),
    )

    assert [trend["views"] for trend in selected] == [
        50_000,
        40_000,
        30_000,
    ]


def test_trending_voice_never_uses_edge_when_fish_fails(monkeypatch, tmp_path):
    service = MediaService.__new__(MediaService)
    service.default_voice = "pt-BR-AntonioNeural"
    monkeypatch.setattr(
        service,
        "_try_fish_voice",
        lambda *_args, **_kwargs: (None, 0.0),
    )

    with pytest.raises(NoFaithfulVoiceError, match="Edge TTS"):
        service._synthesize_voice(
            "Texto de teste com informação suficiente.",
            "pt-BR-AntonioNeural",
            str(tmp_path),
            "pt",
            allow_edge_fallback=False,
        )


def test_trending_script_disables_emergency_fallback(monkeypatch):
    service = ContentService.__new__(ContentService)
    service.client = object()
    monkeypatch.setattr(
        service,
        "_get_best_model",
        lambda: (_ for _ in ()).throw(RuntimeError("provedores fora")),
    )

    with pytest.raises(RuntimeError, match="sem fallback"):
        service.generate_script(
            "Tema específico",
            "pt",
            allow_fallback=False,
        )


def test_trending_metadata_disables_emergency_fallback(monkeypatch):
    service = MetadataService.__new__(MetadataService)
    service.client = object()
    monkeypatch.setattr(service, "_get_best_model", lambda: "modelo")
    monkeypatch.setattr(
        service,
        "_build_metadata_prompt",
        lambda **_kwargs: "prompt",
    )
    monkeypatch.setattr(
        service,
        "_generate_with_ai",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("provedores fora")
        ),
    )

    with pytest.raises(RuntimeError, match="sem fallback"):
        service.build_metadata(
            topic="Tema específico",
            script="Roteiro completo e específico.",
            geo="BR",
            research_context="Contexto real.",
            allow_fallback=False,
        )


def test_trending_maximum_duration_is_three_minutes(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ATLAS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv(
        "ATLAS_MAX_VIDEO_DURATION_SECONDS",
        raising=False,
    )

    service = MediaService()

    assert service.max_video_duration_seconds == 180.0
