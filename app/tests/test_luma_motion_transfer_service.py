from app.services.luma_motion_transfer_service import (
    LumaMotionTransferService,
)


def test_luma_requires_api_key():
    service = LumaMotionTransferService(api_key="")

    assert service.is_configured() is False


def test_luma_rejects_uncontrolled_mode():
    service = LumaMotionTransferService(api_key="test")

    try:
        service.submit(
            guide_video_path="missing.mp4",
            first_frame_path="missing.png",
            prompt="test",
            mode="reimagine_3",
        )
    except ValueError as error:
        assert "Modo Luma" in str(error)
    else:
        raise AssertionError("reimagine mode should be rejected")
