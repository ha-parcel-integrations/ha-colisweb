"""Tests for the Colisweb API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.colisweb.api import (
    ColiswebApiClient,
    ColiswebApiError,
)

from .payloads import delivered_sample

CODE = "10000001"


def _session_returning(
    status: int, body: object = None, headers: dict | None = None
) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_posts_the_number_and_returns_the_reply():
    session = _session_returning(200, delivered_sample(CODE))
    client = ColiswebApiClient(session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel == delivered_sample(CODE)
    assert session.post.call_args[0][0] == "https://www.colisweb.com/api/search"
    assert session.post.call_args[1]["json"] == {"value": CODE}


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_get_parcel_returns_none_for_not_found_statuses(status):
    client = ColiswebApiClient(_session_returning(status, {"error": "x"}))
    assert await client.async_get_parcel(CODE) is None


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_get_parcel_never_treats_a_5xx_as_not_found(status):
    """An empty 500 is an unknown number and a broken backend alike."""
    client = ColiswebApiClient(_session_returning(status, ""))
    with pytest.raises(ColiswebApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == status


async def test_get_parcel_raises_on_a_mismatched_echo():
    client = ColiswebApiClient(_session_returning(200, delivered_sample("99999999")))
    with pytest.raises(ColiswebApiError, match="echo"):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_when_the_echo_is_missing():
    reply = delivered_sample(CODE)
    del reply["searchValue"]
    client = ColiswebApiClient(_session_returning(200, reply))
    with pytest.raises(ColiswebApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = ColiswebApiClient(_session_returning(200, "not json"))
    with pytest.raises(ColiswebApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = ColiswebApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(ColiswebApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_429_carries_retry_after():
    client = ColiswebApiClient(_session_returning(429, None, {"Retry-After": "30"}))
    with pytest.raises(ColiswebApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 429
    assert err.value.retry_after == 30.0


@pytest.mark.parametrize("header", [None, "Wed, 21 Oct 2026 07:28:00 GMT"])
async def test_get_parcel_429_without_usable_retry_after(header):
    headers = {"Retry-After": header} if header else {}
    client = ColiswebApiClient(_session_returning(429, None, headers))
    with pytest.raises(ColiswebApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.retry_after is None


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone -- DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = ColiswebApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
