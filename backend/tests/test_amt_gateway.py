"""The gateway in front of the API sometimes answers a bare ``404 page not found``.

That is not the API saying a resource is missing, it is the route being lost
for a moment, and it goes away on retry. A genuine API 404 is JSON and fatal.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
import pytest
import respx

from antilethe.config import Settings
from antilethe.ingest.amt_client import AMTClient, AMTError
from sample_archive import DAYS, sample_day

BASE = "https://amt.invalid/services/amt/api/v1"


@pytest.fixture
def client_settings(tmp_path: Any) -> Settings:
    return Settings(
        amt_base_url=BASE, db_path=tmp_path / "a.db", rate_limit_per_min=100000, max_retries=3
    )


def _gateway_404() -> httpx.Response:
    return httpx.Response(404, text="404 page not found\n", headers={"content-type": "text/plain"})


@respx.mock
async def test_gateway_404_is_retried_and_the_export_still_lands(
    client_settings: Settings,
) -> None:
    body = "\n".join(json.dumps(r) for r in sample_day(DAYS[0]))
    route = respx.get(url__startswith=f"{BASE}/exports/responses/").mock(
        side_effect=[_gateway_404(), httpx.Response(200, content=gzip.compress(body.encode()))]
    )
    paged = respx.get(url__startswith=f"{BASE}/responses/")

    async with AMTClient(client_settings) as client:
        rows = await client.fetch_day(DAYS[0])

    assert len(rows) == len(sample_day(DAYS[0]))
    assert route.call_count == 2
    # The fallback was never needed.
    assert paged.call_count == 0


@respx.mock
async def test_json_404_from_the_api_is_fatal(client_settings: Settings) -> None:
    route = respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError, match="404"):
            await client.fetch_questions()
    assert route.call_count == 1


@respx.mock
async def test_when_both_routes_fail_the_export_error_is_reported_too(
    client_settings: Settings,
) -> None:
    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(
        return_value=httpx.Response(200, content=b"not gzip at all")
    )
    respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(400, json={"detail": "bad day"})
    )
    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError) as caught:
            await client.fetch_day(DAYS[0])
    message = str(caught.value)
    assert "returned 400" in message
    assert "bulk export had failed first" in message
    assert "not gzip" in message
