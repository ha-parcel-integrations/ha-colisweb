"""Tests for Colisweb diagnostics."""

from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.colisweb.diagnostics import async_get_config_entry_diagnostics
from custom_components.colisweb.parcels import normalize_parcel

from .payloads import delivered_sample


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": "12345678"}]}
    entry.runtime_data.coordinator.current_tier_minutes = 15
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=15)
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "12345678",
            "sender": "Example Shop",
            "receiver": "Jane Doe",
            "status": "out_for_delivery",
            "raw": {
                "searchValue": "12345678",
                "recipient": "Jane Doe",
                "deliveryAddress": {"city": "Rotterdam", "street": "Coolsingel 1"},
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {
        "incoming_active": 1,
        "delivered": 0,
        "skipped_from_fetch": 0,
    }
    assert result["polling"] == {
        "tier_minutes": 15,
        "update_interval_seconds": 900.0,
        "suspended": False,
    }
    # tracking codes and payload PII are redacted, at every nesting level
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["receiver"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["recipient"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["deliveryAddress"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"


async def test_diagnostics_redacts_every_identifying_reply_field(hass):
    """A full reply, with a recipient block, must leave nothing identifying."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = 45
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=45)
    entry.runtime_data.coordinator.delivered_codes = set()
    entry.runtime_data.coordinator.delivered = []
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    parcel["raw"]["recipient"] = {"name": "Jane Doe", "city": "Exampleville"}
    parcel["raw"]["deliveryUuid"] = "00000000-0000-0000-0000-000000000000"
    entry.runtime_data.coordinator.data = [parcel]

    result = await async_get_config_entry_diagnostics(hass, entry)

    text = str(result)
    for leaked in (
        "EXAMPLE RETAILER",
        "Jane Doe",
        "Exampleville",
        "00000000-0000-0000-0000-000000000000",
        "10000001",
        "2026-04-29",
        "2025-12-28",
    ):
        assert leaked not in text
    assert result["incoming"][0]["status"] == "delivered"
    assert result["incoming"][0]["raw"]["step"] == "delivered"


async def test_diagnostics_reports_suspended_polling(hass):
    """update_interval None (Section 2.1's full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }
