from unittest.mock import Mock, patch

from app.services.marketing_service import MarketingService


def _response(payload, status_code=200):
    response = Mock()
    response.content = b"{}"
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response


def test_meta_campaign_snapshot_normalizes_metrics():
    service = object.__new__(MarketingService)
    responses = [
        _response(
            {
                "name": "Campaign",
                "status": "PAUSED",
                "effective_status": "PAUSED",
                "start_time": "2026-08-30T00:00:00-0300",
                "stop_time": "2026-09-06T00:00:00-0300",
            }
        ),
        _response(
            {
                "data": [
                    {
                        "spend": "12.34",
                        "impressions": "1000",
                        "reach": "800",
                        "clicks": "30",
                        "inline_link_clicks": "20",
                        "ctr": "3.0",
                        "cpc": "0.41",
                        "cpm": "12.34",
                        "frequency": "1.25",
                        "actions": [
                            {"action_type": "landing_page_view", "value": "15"}
                        ],
                    }
                ]
            }
        ),
    ]

    with patch("requests.get", side_effect=responses):
        result = service._meta_campaign_snapshot("123", "token")

    assert result["status"] == "paused"
    assert result["spend"] == 12.34
    assert result["impressions"] == 1000
    assert result["link_clicks"] == 20
    assert result["landing_page_views"] == 15
    assert result["ctr"] == 3.0


def test_meta_campaign_snapshot_explains_missing_ads_read():
    service = object.__new__(MarketingService)
    response = _response(
        {"error": {"message": "Authorization Error"}},
        status_code=400,
    )

    with patch("requests.get", return_value=response):
        try:
            service._meta_campaign_snapshot("123", "token")
        except RuntimeError as exc:
            assert "ads_read" in str(exc)
        else:
            raise AssertionError("Expected missing ads_read permission to fail")
