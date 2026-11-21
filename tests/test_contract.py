"""The parcel contract's checks, run over every normalised sample."""

from datetime import date, datetime

import pytest

from custom_components.colisweb.const import ParcelStatus
from custom_components.colisweb.parcels import normalize_parcel, parse_iso

from .payloads import active_sample, delivered_sample

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


def _with_step(step: str) -> dict:
    sample = active_sample()
    sample["step"] = step
    return sample


def _moment_only() -> dict:
    sample = active_sample()
    sample["startsAt"] = "2026-04-29T13:00:00Z"
    sample["endsAt"] = None
    return sample


def _date_only() -> dict:
    sample = active_sample()
    sample["startsAt"] = "2026-04-29"
    sample["endsAt"] = None
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "returning": lambda: _with_step("package_returned"),
    "problem": lambda: _with_step("non_deliverable"),
    "moment_only": _moment_only,
    "date_only": _date_only,
    "bare": lambda: {"searchValue": "30000003"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_delivered_at_is_the_delivery_date():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["delivered_at"] == "2026-04-29T13:12:42.000Z"


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_planned_is_kept_while_the_parcel_is_active():
    parcel = normalize_parcel(active_sample())
    assert parcel["planned_from"] == "2026-04-29T13:00:00Z"
    assert parcel["planned_to"] == "2026-04-29T15:00:00Z"


def test_pickup_is_a_constant_false_without_a_point(parcel):
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_a_moment_ends_at_the_end_of_the_local_day():
    parcel = normalize_parcel(_moment_only())
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert end.utcoffset().total_seconds() == 2 * 3600
    assert end.date() == date(2026, 4, 29)


def test_a_late_moment_has_no_window_end():
    sample = _moment_only()
    sample["startsAt"] = "2026-04-29T21:59:59Z"
    assert normalize_parcel(sample)["planned_to"] is None


def test_a_date_covers_the_whole_day():
    parcel = normalize_parcel(_date_only())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert start.date() == end.date()
