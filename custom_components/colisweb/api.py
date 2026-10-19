"""Colisweb public tracking API client."""
from __future__ import annotations

from typing import Any

import aiohttp

from .const import TRACKING_API_URL

# Answers that mean "this number does not exist". Any other non-200 (notably
# the empty HTTP 500) is indistinguishable from a backend failure.
NOT_FOUND_STATUSES = frozenset({400, 404, 422})


class ColiswebApiError(Exception):
    """Raised when a Colisweb API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Colisweb API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class ColiswebApiClient:
    """Client for the public Colisweb tracking endpoint (keyless)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the reply object for a known number and ``None`` when the
        endpoint rejects it as unknown. Everything else, including an empty
        HTTP 500, raises :class:`ColiswebApiError`; network errors propagate as
        ``aiohttp.ClientError``.
        """
        async with self._session.post(
            TRACKING_API_URL, json={"value": tracking_code}
        ) as response:
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = (
                        float(retry_after_header) if retry_after_header else None
                    )
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds
                raise ColiswebApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status in NOT_FOUND_STATUSES:
                return None
            if response.status != 200:
                raise ColiswebApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                # content_type=None: the route may serve JSON as text/plain.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise ColiswebApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise ColiswebApiError("unexpected body (not a JSON object)")
        if str(payload.get("searchValue")) != tracking_code:
            raise ColiswebApiError("reply does not echo the requested number")
        return payload
