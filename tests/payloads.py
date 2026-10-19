"""Synthetic Colisweb replies shared by the test modules.

Every value is invented; only the key set, nullability and timestamp formats
follow the shape of a live reply.
"""
from __future__ import annotations

ACTIVE_CODE = "20000002"
DELIVERED_CODE = "10000001"


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A delivery under way, with a slot and the first two milestones set."""
    return {
        "step": "out_for_delivery",
        "clientName": "EXAMPLE RETAILER",
        "haveReschedule": False,
        "inRescheduleProcess": False,
        "deliveryUuid": None,
        "startsAt": "2026-04-29T13:00:00Z",
        "endsAt": "2026-04-29T15:00:00Z",
        "deliveredDate": None,
        "deliveryConfirmationDate": "2026-04-27T09:30:00.000Z",
        "pickedUpDate": "2026-04-28T15:52:17.000Z",
        "searchValue": code,
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """A delivered reply: every milestone set."""
    sample = active_sample(code)
    sample.update(
        {
            "step": "delivered",
            "deliveredDate": "2026-04-29T13:12:42.000Z",
        }
    )
    return sample


def non_deliverable_sample(code: str = DELIVERED_CODE) -> dict:
    """The one step seen live: past slot, only the confirmation milestone."""
    sample = active_sample(code)
    sample.update(
        {
            "step": "non_deliverable",
            "startsAt": "2026-01-01T10:00:00Z",
            "endsAt": "2026-01-01T12:00:00Z",
            "deliveryConfirmationDate": "2025-12-28T13:00:00.000Z",
            "pickedUpDate": None,
        }
    )
    return sample
