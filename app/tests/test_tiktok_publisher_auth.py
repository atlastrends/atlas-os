from unittest.mock import Mock, patch

from app.publishing.base import PublishRequest
from app.publishing.tiktok.publisher import TikTokPublisher


def test_tiktok_upload_uses_bearer_token(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    monkeypatch.setenv("TIKTOK_DIRECT_POST", "false")

    init_response = Mock()
    init_response.status_code = 200
    init_response.json.return_value = {
        "data": {
            "publish_id": "publish-1",
            "upload_url": "https://upload.example/video",
        },
        "error": {"code": "ok"},
    }
    put_response = Mock(status_code=200)
    request = PublishRequest(
        video_path=str(video),
        title="Product",
        description="",
        caption="Product",
        hashtags=[],
        language="en",
        country_code="US",
    )

    with (
        patch(
            "app.publishing.tiktok.publisher.tiktok_oauth_service.get_access_token",
            return_value="access-token",
        ),
        patch(
            "app.publishing.tiktok.publisher.requests.post",
            return_value=init_response,
        ) as post,
        patch(
            "app.publishing.tiktok.publisher.requests.put",
            return_value=put_response,
        ),
    ):
        result = TikTokPublisher()._do_publish(request)

    assert result.status == "published"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer access-token"
