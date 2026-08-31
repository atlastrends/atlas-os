from app.services.publishing_service import _is_rate_limited


def test_facebook_frequency_protection_is_temporary_rate_limit():
    error = (
        "Limitamos a frequência com que você pode postar. "
        "Você pode tentar novamente mais tarde. "
        "{'code': 368, 'error_subcode': 1390008}"
    )

    assert _is_rate_limited(error)
