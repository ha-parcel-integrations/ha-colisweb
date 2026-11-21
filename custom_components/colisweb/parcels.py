"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

The carrier-specific parts are :data:`_STATUS_MAP`, the milestone history and
:func:`normalize_parcel`; the timestamp parsing, the sort contract, the
delivered filter and the one-shot warnings are suite-wide machinery.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# The slot is wall-clock time in France and Belgium, which share a zone.
_ZONE = ZoneInfo("Europe/Paris")

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-colisweb/issues/new"
    "?template=unrecognised_status.yml"
)

# Keys are the reply's ``step`` lower-cased with ``_``/``-`` removed (see
# :func:`_step_key`). Only ``nondeliverable`` has been seen on the wire; the
# rest of the vocabulary is unconfirmed, so an unlisted step reports
# ``unknown`` plus a one-shot warning.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "idle": ParcelStatus.REGISTERED,
    "confirmed": ParcelStatus.REGISTERED,
    "courseaccepted": ParcelStatus.REGISTERED,
    "pickedup": ParcelStatus.IN_TRANSIT,
    "packagewithdrawn": ParcelStatus.IN_TRANSIT,
    "packagewithdrawalpbok": ParcelStatus.IN_TRANSIT,
    "outfordelivery": ParcelStatus.OUT_FOR_DELIVERY,
    "deliveryinprogress": ParcelStatus.OUT_FOR_DELIVERY,
    "delivered": ParcelStatus.DELIVERED,
    "deliverypbok": ParcelStatus.DELIVERED,
    "pickupfailed": ParcelStatus.PROBLEM,
    "packagewithdrawalfailed": ParcelStatus.PROBLEM,
    "deliveryfailed": ParcelStatus.PROBLEM,
    "nondeliverable": ParcelStatus.PROBLEM,
    "canceled": ParcelStatus.PROBLEM,
    "cancelled": ParcelStatus.PROBLEM,
    "deliverycanceled": ParcelStatus.PROBLEM,
    "deliverycancelled": ParcelStatus.PROBLEM,
    "packagereturned": ParcelStatus.RETURNING,
    "deliveryreturned": ParcelStatus.RETURNING,
    "packagereturnfailed": ParcelStatus.RETURNING,
    "deliveryreturnfailed": ParcelStatus.RETURNING,
}

# Every key the reply is known to carry. Anything else is reported once.
_KNOWN_KEYS = frozenset(
    {
        "step",
        "clientName",
        "haveReschedule",
        "inRescheduleProcess",
        "deliveryUuid",
        "startsAt",
        "endsAt",
        "deliveredDate",
        "deliveryConfirmationDate",
        "pickedUpDate",
        "searchValue",
    }
)

# Steps seen on a real reply. Every other mapped step is a derived guess.
_CONFIRMED_STEPS = frozenset({"nondeliverable"})

# Milestone timestamp fields, oldest stage first.
_MILESTONES: tuple[tuple[str, ParcelStatus], ...] = (
    ("deliveryConfirmationDate", ParcelStatus.REGISTERED),
    ("pickedUpDate", ParcelStatus.IN_TRANSIT),
    ("deliveredDate", ParcelStatus.DELIVERED),
)

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Colisweb status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def _step_key(step: str) -> str:
    """Normalise a ``step`` value for lookup in :data:`_STATUS_MAP`."""
    return str(step).lower().replace("_", "").replace("-", "")


def map_parcel_status(step: str | None) -> ParcelStatus:
    """Map the reply's ``step`` to a canonical :class:`ParcelStatus`.

    ``None`` (a placeholder for a number not looked up yet) reports ``unknown``
    silently; an unrecognised step reports ``unknown`` with a one-shot warning,
    and so does a mapped step no real parcel has confirmed yet.
    """
    if not step:
        return ParcelStatus.UNKNOWN
    key = _step_key(step)
    mapped = _STATUS_MAP.get(key)
    if mapped is not None:
        if key not in _CONFIRMED_STEPS:
            _warn_once(
                "unconfirmed:" + key,
                "Colisweb reported step '%s', which this integration reads as "
                "'%s'. That reading is derived, not seen on a real parcel — "
                "please confirm it looks right. Open an issue and paste this "
                "line: %s",
                step,
                mapped,
                NEW_ISSUE_URL,
            )
        return mapped
    _warn_unmapped_status(step)
    return ParcelStatus.UNKNOWN


def _status_from_milestones(raw: dict) -> ParcelStatus:
    """Newest stage a milestone timestamp proves, for a step we cannot map."""
    for field, stage in reversed(_MILESTONES):
        if raw.get(field):
            return stage
    return ParcelStatus.UNKNOWN


def _warn_once(key: str, message: str, *args: Any) -> None:
    """Log a warning once per HA session, keyed on ``key``."""
    if key in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(key)
    _LOGGER.warning(message, *args)


def _warn_unexpected_shape(raw: dict) -> None:
    """Warn once, keys only, about reply shapes not seen on the wire."""
    extra = sorted(set(raw) - _KNOWN_KEYS - {"recipient"})
    if extra:
        _warn_once(
            "keys:" + ",".join(extra),
            "Unexpected Colisweb reply fields — help us map them. Open an issue "
            "and paste this line: %s\n  keys=%s",
            NEW_ISSUE_URL,
            ", ".join(extra),
        )
    if "recipient" in raw:
        _warn_once(
            "shape:recipient",
            "Colisweb reply carries a recipient block (never published, kept out "
            "of diagnostics) — help us map it. Open an issue and paste this "
            "line: %s\n  keys=recipient",
            NEW_ISSUE_URL,
        )
    if raw.get("deliveryUuid") is not None:
        _warn_once(
            "shape:deliveryUuid",
            "Colisweb reply carries a non-null deliveryUuid — help us map it. "
            "Open an issue and paste this line: %s\n  keys=deliveryUuid",
            NEW_ISSUE_URL,
        )


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def build_history(
    raw: dict,
    status: ParcelStatus,
    step: str | None,
    *,
    max_events: int = HISTORY_MAX_EVENTS,
) -> list[dict]:
    """Build the canonical ``history`` list from the reply's milestones.

    The reply holds no event list, only three milestone timestamps. Each
    non-null one becomes an entry, oldest first; when none of them carries the
    current step's stage, a time-less entry for the step itself is appended.
    """
    dated: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for field, stage in _MILESTONES:
        timestamp = to_iso_timestamp(raw.get(field))
        if not timestamp:
            continue
        entry = {"timestamp": timestamp, "status": stage, "raw_status": field}
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            dated.append((parsed, entry))
    dated.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in dated] + unparseable
    if step and not any(entry["status"] is status for entry in ordered):
        ordered.append(
            {
                "timestamp": None,
                "status": None if status is ParcelStatus.UNKNOWN else status,
                "raw_status": step,
            }
        )
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def _moment(value: Any, zone: tzinfo) -> tuple[datetime, bool, str] | None:
    """Return ``(aware datetime, date_only, text)`` for a carrier time, or ``None``.

    A naive time or a bare date gets ``zone``; an aware time keeps its offset
    and, when it came in as a string, its own spelling.
    """
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        moment = datetime.combine(value, time.min, tzinfo=zone)
        return moment, True, moment.isoformat()
    elif isinstance(value, str) and value:
        try:
            if len(value) == 10:
                moment = datetime.combine(
                    date.fromisoformat(value), time.min, tzinfo=zone
                )
                return moment, True, moment.isoformat()
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed, False, value
    else:
        return None
    moment = parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
    return moment, False, moment.isoformat()


def _end_of_day(moment: datetime, zone: tzinfo) -> datetime:
    local = moment.astimezone(zone)
    return datetime.combine(local.date(), time(23, 59, 59), tzinfo=zone)


def planned_window(
    start: Any, end: Any, *, zone: tzinfo
) -> tuple[str | None, str | None]:
    """Return ``(planned_from, planned_to)`` in the canonical window shape.

    ``start`` and ``end`` are ISO strings, dates or datetimes, or ``None``; an
    epoch number must be converted first (see ``to_iso_timestamp``). A window
    keeps both ends. One moment with a time ends at ``23:59:59`` the same local
    day; a date covers ``00:00:00`` to ``23:59:59``; two dates run from the
    first day's start to the last day's end. Equal values are one moment,
    reversed values are swapped, and ``planned_to`` is never set without
    ``planned_from``. ``zone`` is the carrier's own zone: it dates naive times
    and bare dates and decides which day a moment ends on, so a ``Z`` moment
    still ends on the carrier's local day. When nothing is left of that day
    after the moment, there is no ``planned_to``.
    """
    first = _moment(start, zone)
    last = _moment(end, zone)
    if first is None:
        first, last = last, None
    if first is None:
        return None, None

    def closing(moment: tuple[datetime, bool, str]) -> datetime:
        return _end_of_day(moment[0], zone) if moment[1] else moment[0]

    if last is not None and closing(last) < first[0]:
        first, last = last, first
    if last is not None and closing(last) == first[0]:
        last = None

    if last is None:
        end_of_day = _end_of_day(first[0], zone)
        return first[2], end_of_day.isoformat() if end_of_day > first[0] else None
    return first[2], closing(last).isoformat() if last[1] else last[2]


_NO_WINDOW_STATUSES = frozenset(
    {ParcelStatus.AT_PICKUP_POINT, ParcelStatus.RETURNING, ParcelStatus.DELIVERED}
)


def planned_for_status(
    status: ParcelStatus, planned_from: str | None, planned_to: str | None
) -> tuple[str | None, str | None]:
    """Empty the delivery window once the parcel is at its destination or done."""
    if status in _NO_WINDOW_STATUSES:
        return None, None
    return planned_from, planned_to


def is_pickup(
    route_flag: bool | None,
    status: ParcelStatus,
    event_statuses: Iterable[ParcelStatus | None] = (),
) -> bool:
    """Whether the delivery route ends at a pickup point.

    The carrier's own route flag wins; otherwise the parcel having reached
    ``AT_PICKUP_POINT`` at any point counts, so the value survives collection.
    """
    if route_flag:
        return True
    return status is ParcelStatus.AT_PICKUP_POINT or any(
        event is ParcelStatus.AT_PICKUP_POINT for event in event_statuses
    )


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The reply is a flat object about one appointment: a slot (``startsAt`` /
    ``endsAt``) plus three milestone timestamps. The slot is published until the
    parcel is returning or delivered, unless it has been rescheduled. A step that does not map
    falls back to the newest milestone before it reports ``unknown``.
    """
    _warn_unexpected_shape(raw)
    number = raw.get("searchValue")
    step = raw.get("step")
    mapped = map_parcel_status(step)
    status = mapped
    if status is ParcelStatus.UNKNOWN:
        status = _status_from_milestones(raw)
    delivered = status is ParcelStatus.DELIVERED

    rescheduling = bool(raw.get("haveReschedule") or raw.get("inRescheduleProcess"))
    planned_from = planned_to = None
    if not rescheduling:
        planned_from, planned_to = planned_window(
            to_iso_timestamp(raw.get("startsAt")),
            to_iso_timestamp(raw.get("endsAt")),
            zone=_ZONE,
        )
    planned_from, planned_to = planned_for_status(status, planned_from, planned_to)

    return {
        "carrier": "Colisweb",
        "barcode": number,
        "sender": raw.get("clientName") or None,
        "receiver": None,
        "status": status,
        "raw_status": step,
        "delivered": delivered,
        "delivered_at": to_iso_timestamp(raw.get("deliveredDate"))
        if delivered
        else None,
        "planned_from": planned_from,
        "planned_to": planned_to,
        "pickup": is_pickup(None, status),
        "pickup_point": None,
        "url": tracking_url(number),
        "weight": None,
        "dimensions": None,
        "history": build_history(raw, mapped, step) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
