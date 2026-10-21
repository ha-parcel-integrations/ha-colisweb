"""Tests for the pure parcel-mapping helpers."""

from datetime import UTC, datetime, timedelta
import logging

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.colisweb.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    PENDING_CAPABILITIES,
    ParcelStatus,
)
from custom_components.colisweb.parcels import (
    apply_delivered_filter,
    build_history,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    sort_parcels_by_ts,
    to_iso_timestamp,
    tracking_url,
)

from .payloads import (
    DELIVERED_CODE,
    active_sample,
    delivered_sample,
    non_deliverable_sample,
)

# ---------------------------------------------------------------------------
# map_parcel_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("idle", ParcelStatus.REGISTERED),
        ("confirmed", ParcelStatus.REGISTERED),
        ("course_accepted", ParcelStatus.REGISTERED),
        ("picked_up", ParcelStatus.IN_TRANSIT),
        ("package_withdrawn", ParcelStatus.IN_TRANSIT),
        ("package_withdrawal_pbok", ParcelStatus.IN_TRANSIT),
        ("out_for_delivery", ParcelStatus.OUT_FOR_DELIVERY),
        ("delivery_in_progress", ParcelStatus.OUT_FOR_DELIVERY),
        ("delivered", ParcelStatus.DELIVERED),
        ("delivery_pbok", ParcelStatus.DELIVERED),
        ("pickup_failed", ParcelStatus.PROBLEM),
        ("package_withdrawal_failed", ParcelStatus.PROBLEM),
        ("delivery_failed", ParcelStatus.PROBLEM),
        ("non_deliverable", ParcelStatus.PROBLEM),
        ("canceled", ParcelStatus.PROBLEM),
        ("cancelled", ParcelStatus.PROBLEM),
        ("delivery_canceled", ParcelStatus.PROBLEM),
        ("delivery_cancelled", ParcelStatus.PROBLEM),
        ("package_returned", ParcelStatus.RETURNING),
        ("delivery_returned", ParcelStatus.RETURNING),
        ("package_return_failed", ParcelStatus.RETURNING),
        ("delivery_return_failed", ParcelStatus.RETURNING),
    ],
)
def test_map_parcel_status_known(step, expected):
    assert map_parcel_status(step) == expected


@pytest.mark.parametrize(
    "variant",
    ["NON_DELIVERABLE", "non-deliverable", "NonDeliverable", "nondeliverable"],
)
def test_map_parcel_status_ignores_case_and_separators(variant):
    assert map_parcel_status(variant) == ParcelStatus.PROBLEM


def test_failed_withdrawal_is_a_problem_not_in_transit():
    """The failed variants share a stem with the in-transit ones."""
    assert map_parcel_status("package_withdrawal_failed") == ParcelStatus.PROBLEM
    assert map_parcel_status("package_withdrawn") == ParcelStatus.IN_TRANSIT
    assert map_parcel_status("delivery_return_failed") == ParcelStatus.RETURNING


def test_map_parcel_status_missing_is_unknown():
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status("") == ParcelStatus.UNKNOWN


def test_map_parcel_status_unmapped_is_unknown():
    assert map_parcel_status("teleported") == ParcelStatus.UNKNOWN


def test_unmapped_status_warns_only_once(caplog):
    assert map_parcel_status("abducted") == ParcelStatus.UNKNOWN
    assert map_parcel_status("abducted") == ParcelStatus.UNKNOWN
    assert caplog.text.count("abducted") == 1
    assert "issues/new" in caplog.text


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    # A naive value is assumed UTC so mixed lists still sort.
    assert parse_iso("2026-04-29T13:12:42").tzinfo == UTC
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_converts_epoch_milliseconds():
    assert to_iso_timestamp(1784203767167) == "2026-07-16T12:09:27.167000+00:00"
    assert to_iso_timestamp("2026-04-29T13:12:42Z") == "2026-04-29T13:12:42Z"
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**20) is None  # out of range -> None, never raises


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------


def test_build_history_orders_milestones_oldest_first():
    raw = delivered_sample()
    history = build_history(raw, ParcelStatus.DELIVERED, raw["step"])
    assert [entry["status"] for entry in history] == [
        ParcelStatus.REGISTERED,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.DELIVERED,
    ]
    assert history[0]["raw_status"] == "deliveryConfirmationDate"


def test_build_history_adds_a_timeless_entry_for_an_uncovered_step():
    raw = non_deliverable_sample()
    history = build_history(raw, ParcelStatus.PROBLEM, raw["step"])
    assert [entry["status"] for entry in history] == [
        ParcelStatus.REGISTERED,
        ParcelStatus.PROBLEM,
    ]
    assert history[-1] == {
        "timestamp": None,
        "status": ParcelStatus.PROBLEM,
        "raw_status": "non_deliverable",
    }


def test_build_history_has_no_extra_entry_when_a_milestone_carries_the_stage():
    raw = active_sample()
    raw["step"] = "picked_up"
    history = build_history(raw, ParcelStatus.IN_TRANSIT, raw["step"])
    assert len(history) == 2


def test_build_history_unmapped_step_keeps_status_null():
    raw = active_sample()
    raw["step"] = "teleported"
    history = build_history(raw, ParcelStatus.UNKNOWN, raw["step"])
    assert history[-1]["status"] is None
    assert history[-1]["raw_status"] == "teleported"


def test_build_history_empty_without_milestones_or_step():
    assert build_history({"searchValue": "1"}, ParcelStatus.UNKNOWN, None) == []


def test_build_history_keeps_unparseable_timestamp_last():
    raw = active_sample()
    raw["deliveryConfirmationDate"] = "not-a-date"
    history = build_history(raw, ParcelStatus.OUT_FOR_DELIVERY, raw["step"])
    assert [entry["raw_status"] for entry in history] == [
        "pickedUpDate",
        "deliveryConfirmationDate",
        "out_for_delivery",
    ]


def test_build_history_caps_to_max_events():
    raw = delivered_sample()
    assert (
        len(build_history(raw, ParcelStatus.DELIVERED, "delivered", max_events=2)) == 2
    )


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    """A typo here would silently misreport this carrier on the docs site."""
    assert CAPABILITIES <= KNOWN_CAPABILITIES
    assert PENDING_CAPABILITIES <= KNOWN_CAPABILITIES


def test_a_capability_is_never_both_populated_and_pending():
    """The docs site would have to pick one; "awaiting data" must not hide a confirmed field."""
    assert not CAPABILITIES & PENDING_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    """Every declared CAPABILITIES entry must come true on a sample."""
    delivered = normalize_parcel(delivered_sample())
    active = normalize_parcel(active_sample())
    with_history = normalize_parcel(delivered_sample(), include_history=True)

    if "weight" in CAPABILITIES:
        assert delivered["weight"] is not None
    if "dimensions" in CAPABILITIES:
        assert delivered["dimensions"] is not None
    if "delivery_window" in CAPABILITIES:
        assert active["planned_from"] is not None or active["planned_to"] is not None
    if "pickup_point" in CAPABILITIES:
        assert delivered["pickup_point"] is not None
    if "url" in CAPABILITIES:
        assert delivered["url"] is not None
    if "history" in CAPABILITIES:
        assert with_history["history"] is not None


def test_pending_delivery_window_is_still_populated_in_flight():
    """Pending means "not seen live", not "never filled" -- the code path exists."""
    assert normalize_parcel(active_sample())["planned_from"] is not None


def test_normalize_delivered_parcel():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["carrier"] == "Colisweb"
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["sender"] == "EXAMPLE RETAILER"
    assert parcel["receiver"] is None
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "delivered"
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-04-29T13:12:42.000Z"
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None
    assert parcel["url"] == (
        f"https://www.colisweb.com/suivi-livraison?tracking={DELIVERED_CODE}"
    )
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None
    assert parcel["history"] is None  # opt-in, default off


def test_normalize_history_is_opt_in():
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    assert len(parcel["history"]) == 3
    assert parcel["history"][0]["status"] == ParcelStatus.REGISTERED


def test_normalize_active_parcel_has_window():
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] == ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None
    assert parcel["planned_from"] == "2026-04-29T13:00:00Z"
    assert parcel["planned_to"] == "2026-04-29T15:00:00Z"


@pytest.mark.parametrize("flag", ["haveReschedule", "inRescheduleProcess"])
def test_normalize_hides_the_slot_while_rescheduling(flag):
    raw = active_sample()
    raw[flag] = True
    parcel = normalize_parcel(raw)
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


def test_normalize_hides_the_slot_once_delivered():
    raw = active_sample()
    raw["step"] = "delivered"
    parcel = normalize_parcel(raw)
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


@pytest.mark.parametrize("step", ["non_deliverable", "package_returned"])
def test_normalize_keeps_the_slot_on_a_failed_or_returned_delivery(step):
    raw = active_sample()
    raw["step"] = step
    parcel = normalize_parcel(raw)
    assert parcel["planned_from"] == "2026-04-29T13:00:00Z"


def test_normalize_non_deliverable_is_a_problem_that_keeps_its_slot():
    raw = non_deliverable_sample()
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.PROBLEM
    assert parcel["delivered"] is False
    assert parcel["planned_from"] == to_iso_timestamp(raw["startsAt"])
    assert parcel["planned_to"] == to_iso_timestamp(raw["endsAt"])
    assert parcel["raw_status"] == "non_deliverable"


def test_normalize_collapses_point_estimate_to_no_window_end():
    raw = active_sample()
    raw["endsAt"] = raw["startsAt"]
    parcel = normalize_parcel(raw)
    assert parcel["planned_from"] == "2026-04-29T13:00:00Z"
    assert parcel["planned_to"] is None


def test_normalize_pending_placeholder():
    """A tracked-but-not-looked-up number still yields a full parcel dict."""
    parcel = normalize_parcel({"searchValue": "30000003"})
    assert parcel["barcode"] == "30000003"
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None
    assert parcel["history"] is None


def test_normalize_blank_sender_becomes_none():
    raw = active_sample()
    raw["clientName"] = ""
    assert normalize_parcel(raw)["sender"] is None


def test_normalize_keeps_raw_payload():
    raw = active_sample()
    assert normalize_parcel(raw)["raw"] is raw


def test_tracking_url_needs_a_number():
    assert tracking_url(None) is None


def test_normalize_drops_a_recipient_block_but_keeps_it_in_raw(caplog):
    raw = active_sample()
    raw["recipient"] = {"name": "Jane Doe", "city": "Exampleville"}
    with caplog.at_level(logging.WARNING):
        parcel = normalize_parcel(raw)
    assert parcel["receiver"] is None
    assert "Jane Doe" not in str({k: v for k, v in parcel.items() if k != "raw"})
    assert parcel["raw"]["recipient"]["name"] == "Jane Doe"
    assert "recipient block" in caplog.text
    assert "Jane Doe" not in caplog.text
    assert "Exampleville" not in caplog.text


def test_unexpected_fields_warn_once_with_keys_only(caplog):
    raw = non_deliverable_sample()
    raw["newField"] = "secret value"
    with caplog.at_level(logging.WARNING):
        normalize_parcel(raw)
        normalize_parcel(raw)
    assert len(caplog.records) == 1
    assert "newField" in caplog.text
    assert "secret value" not in caplog.text
    assert "issues/new" in caplog.text


def test_non_null_delivery_uuid_warns_once_without_the_value(caplog):
    raw = non_deliverable_sample()
    raw["deliveryUuid"] = "uuid-should-not-leak"
    with caplog.at_level(logging.WARNING):
        normalize_parcel(raw)
        normalize_parcel(raw)
    assert len(caplog.records) == 1
    assert "uuid-should-not-leak" not in caplog.text


def test_a_clean_reply_logs_no_shape_warning(caplog):
    with caplog.at_level(logging.WARNING):
        normalize_parcel(non_deliverable_sample())
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(UTC)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels


# ---------------------------------------------------------------------------
# Pre-1.0 confirmation warning and the milestone fallback
# ---------------------------------------------------------------------------


def test_a_mapped_but_unseen_step_warns_once_with_the_step_only(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_parcel_status("pickup_failed") == ParcelStatus.PROBLEM
        assert map_parcel_status("pickup_failed") == ParcelStatus.PROBLEM
    assert len(caplog.records) == 1
    assert "pickup_failed" in caplog.text
    assert "problem" in caplog.text
    assert "issues/new" in caplog.text


def test_the_step_seen_live_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING):
        assert map_parcel_status("non_deliverable") == ParcelStatus.PROBLEM
    assert not caplog.records


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"deliveredDate": "2026-04-29T13:12:42.000Z"}, ParcelStatus.DELIVERED),
        ({}, ParcelStatus.IN_TRANSIT),
        ({"pickedUpDate": None}, ParcelStatus.REGISTERED),
        (
            {"pickedUpDate": None, "deliveryConfirmationDate": None},
            ParcelStatus.UNKNOWN,
        ),
    ],
)
def test_an_unmapped_step_falls_back_to_the_newest_milestone(overrides, expected):
    raw = active_sample()
    raw["step"] = "teleported_somewhere"
    raw.update(overrides)
    parcel = normalize_parcel(raw)
    assert parcel["status"] == expected
    assert parcel["delivered"] is (expected is ParcelStatus.DELIVERED)
    assert parcel["raw_status"] == "teleported_somewhere"


def test_the_fallback_keeps_the_unmapped_step_in_the_history():
    raw = active_sample()
    raw["step"] = "teleported_somewhere"
    history = normalize_parcel(raw, include_history=True)["history"]
    assert history[-1] == {
        "timestamp": None,
        "status": None,
        "raw_status": "teleported_somewhere",
    }
