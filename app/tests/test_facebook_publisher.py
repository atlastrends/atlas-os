from app.publishing.facebook.publisher import _is_reels_frequency_block


def test_detects_reels_frequency_block():
    payload = {
        "error": {
            "message": "Limitamos a frequência com que você pode postar.",
            "code": 368,
            "error_subcode": 1390008,
        }
    }

    assert _is_reels_frequency_block(payload)
