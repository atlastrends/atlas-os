from unittest.mock import Mock

import pytest

from app.services.marketing_service import MarketingService


def test_launch_campaign_requires_explicit_spend_confirmation():
    service = object.__new__(MarketingService)
    service.db = Mock()

    with pytest.raises(PermissionError, match="confirme explicitamente"):
        service.launch_campaign(123)


def test_create_and_publish_requires_explicit_spend_confirmation():
    service = object.__new__(MarketingService)
    service.db = Mock()

    with pytest.raises(PermissionError, match="confirme explicitamente"):
        service.create_campaign(
            video_id=123,
            budget_amount=100,
            publish=True,
        )
