"""The HTTP client: pagination, rate limiting, backoff, and failing loudly."""

from __future__ import annotations

import gzip
import json
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from antilethe.config import Settings
from antilethe.ingest.amt_client import AMTAuthError, AMTClient, AMTError, RateLimiter
from sample_archive import DAYS, sample_day

BASE = "https://amt.invalid/services/amt/api/v1"


@pytest.fixture
def client_settings(tmp_path: Any) -> Settings:
    return Settings(
        amt_base_url=BASE,
        db_path=tmp_path / "a.db",
        rate_limit_per_min=100000,
        max_retries=3,
    )


# ---------------------------------------------------------------------------
# rate limiter
# ---------------------------------------------------------------------------


async def test_rate_limiter_allows_a_burst_up_to_capacity() -> None:
    limiter = RateLimiter(60)
    for _ in range(60):
        await limiter.acquire()


async def test_rate_limiter_blocks_once_drained() -> None:
    import time

    limiter = RateLimiter(60)  # one token per second
    for _ in range(60):
        await limiter.acquire()
    started = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - started > 0.3


# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_questions(client_settings: Settings, sample_payload: dict[str, Any]) -> None:
    respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(200, json=sample_payload["questions"])
    )
    async with AMTClient(client_settings) as client:
        questions = await client.fetch_questions()

    assert [q.slug for q in questions] == [
        "is-coffee-good-for-you",
        "who-invented-the-telescope",
    ]
    assert questions[0].text == "Is coffee good for you?"


@respx.mock
async def test_pagination_follows_next_verbatim(client_settings: Settings) -> None:
    """Page URLs are never constructed; upstream's `next` is followed as given."""
    page_two = f"{BASE}/questions/?cursor=opaque-token&page=2"
    respx.get(f"{BASE}/questions/", params__contains={"enabled": "true"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": page_two,
                "previous": None,
                "results": [{"slug": "a", "question_text": "A?", "tags": [], "enabled": True}],
            },
        )
    )
    second = respx.get(page_two).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "previous": None,
                "results": [{"slug": "b", "question_text": "B?", "tags": [], "enabled": True}],
            },
        )
    )

    async with AMTClient(client_settings) as client:
        questions = await client.fetch_questions()

    assert [q.slug for q in questions] == ["a", "b"]
    assert second.called


@respx.mock
async def test_fetch_models_stamps_the_day(
    client_settings: Settings, sample_payload: dict[str, Any]
) -> None:
    respx.get(url__startswith=f"{BASE}/models/recent/").mock(
        return_value=httpx.Response(200, json=sample_payload["models"])
    )
    async with AMTClient(client_settings) as client:
        models = await client.fetch_models("2026-03-01")

    assert {m.day for m in models} == {"2026-03-01"}
    oracle = next(m for m in models if m.model_id == "closedlab/oracle")
    assert oracle.canonical_slug == "closedlab/oracle-2026-01-15"
    assert oracle.vendor == "closedlab"
    assert oracle.prompt_price == 3e-06


def _export_body(day: str) -> bytes:
    """A gzipped JSONL day export, as upstream serves it."""
    lines = "\n".join(json.dumps(row) for row in sample_day(day))
    return gzip.compress(lines.encode("utf-8"))


@respx.mock
async def test_fetch_day_prefers_the_bulk_export(client_settings: Settings) -> None:
    export = respx.get(url__startswith=f"{BASE}/exports/responses/").mock(
        return_value=httpx.Response(
            200, content=_export_body(DAYS[0]), headers={"content-type": "application/gzip"}
        )
    )
    paged = respx.get(url__startswith=f"{BASE}/responses/")

    async with AMTClient(client_settings) as client:
        rows = await client.fetch_day(date(2026, 3, 1))

    assert export.called
    assert not paged.called
    assert len(rows) == len(sample_day(DAYS[0]))
    assert rows[0].serving_host == "Novita"


@respx.mock
async def test_fetch_day_falls_back_to_pagination(client_settings: Settings) -> None:
    """A truncated or unavailable export must not lose the day."""
    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(
        return_value=httpx.Response(200, content=b"not gzip at all")
    )
    paged = respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(
            200,
            json={"count": 1, "next": None, "previous": None, "results": sample_day(DAYS[0])},
        )
    )

    async with AMTClient(client_settings) as client:
        rows = await client.fetch_day("2026-03-01")

    assert paged.called
    assert len(rows) == len(sample_day(DAYS[0]))


@respx.mock
async def test_paginated_day_requests_full_detail(client_settings: Settings) -> None:
    """Without detail=full there are no turns, and so no serving host."""
    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(return_value=httpx.Response(503))
    route = respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(
            200,
            json={"count": 1, "next": None, "previous": None, "results": sample_day(DAYS[0])},
        )
    )

    async with AMTClient(client_settings) as client:
        await client.fetch_day("2026-03-01")

    assert route.calls
    assert route.calls[0].request.url.params["detail"] == "full"


# ---------------------------------------------------------------------------
# failure behaviour
# ---------------------------------------------------------------------------


@respx.mock
async def test_403_says_a_key_is_required(client_settings: Settings) -> None:
    respx.get(url__startswith=f"{BASE}/questions/").mock(return_value=httpx.Response(403))

    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTAuthError) as caught:
            await client.fetch_questions()

    assert "AMT_KEY" in str(caught.value)


@respx.mock
async def test_429_honours_retry_after(client_settings: Settings) -> None:
    route = respx.get(url__startswith=f"{BASE}/questions/")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"count": 0, "next": None, "previous": None, "results": []}),
    ]

    async with AMTClient(client_settings) as client:
        assert await client.fetch_questions() == []
    assert route.call_count == 2


@respx.mock
async def test_5xx_is_retried_then_fails_loudly(client_settings: Settings) -> None:
    route = respx.get(url__startswith=f"{BASE}/questions/").mock(return_value=httpx.Response(500))

    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError):
            await client.fetch_questions()

    assert route.call_count == client_settings.max_retries


@respx.mock
async def test_4xx_is_fatal_immediately(client_settings: Settings) -> None:
    """page_size out of range is a 400, not a clamp, and must not be retried."""
    route = respx.get(url__startswith=f"{BASE}/questions/").mock(
        return_value=httpx.Response(400, text="page_size out of range")
    )

    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError) as caught:
            await client.fetch_questions()

    assert route.call_count == 1
    assert "400" in str(caught.value)


@respx.mock
async def test_transport_failure_raises_rather_than_returning_nothing(
    client_settings: Settings,
) -> None:
    """Hard rule: an unreachable upstream must never yield an empty dataset."""
    respx.get(url__startswith=f"{BASE}/questions/").mock(
        side_effect=httpx.ConnectError("no route to host")
    )

    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError):
            await client.fetch_questions()


@respx.mock
async def test_empty_export_is_an_error_not_an_empty_day(client_settings: Settings) -> None:
    respx.get(url__startswith=f"{BASE}/exports/responses/").mock(
        return_value=httpx.Response(200, content=gzip.compress(b""))
    )
    paged = respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )

    async with AMTClient(client_settings) as client:
        rows = await client.fetch_day("2026-03-01")

    # The export was rejected and the paged path returned the real answer: none.
    assert rows == []
    assert paged.called


# ---------------------------------------------------------------------------
# discover_range
# ---------------------------------------------------------------------------


@respx.mock
async def test_discover_range_bisects_to_the_first_day(client_settings: Settings) -> None:
    """Days on or after the boundary are non-empty; earlier ones are empty."""
    first = date(2026, 3, 1)

    def handler(request: httpx.Request) -> httpx.Response:
        day = date.fromisoformat(request.url.params["day"])
        count = 10 if day >= first else 0
        return httpx.Response(
            200, json={"count": count, "next": None, "previous": None, "results": []}
        )

    respx.get(url__startswith=f"{BASE}/responses/").mock(side_effect=handler)

    async with AMTClient(client_settings) as client:
        discovered_first, discovered_last = await client.discover_range()

    assert discovered_first == first
    assert discovered_last >= first


@respx.mock
async def test_discover_range_raises_when_nothing_is_archived(
    client_settings: Settings,
) -> None:
    respx.get(url__startswith=f"{BASE}/responses/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )

    async with AMTClient(client_settings) as client:
        with pytest.raises(AMTError):
            await client.discover_range()


def test_rate_limit_follows_whether_a_key_is_present(tmp_path: Any) -> None:
    anonymous = Settings(db_path=tmp_path / "a.db")
    assert anonymous.effective_rate_per_min == 30
    assert anonymous.auth_headers == {}

    keyed = Settings(db_path=tmp_path / "a.db", AMT_KEY="secret")
    assert keyed.effective_rate_per_min == 120
    assert keyed.auth_headers == {"Authorization": "Bearer secret"}
