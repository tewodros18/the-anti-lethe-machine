"""Async client for the Internet Archive's Ask Me Twice API.

Three upstream details drive the shape of this module:

* ``turns`` is absent unless ``detail=full`` is requested, and ``turns[0].provider``
  is the only place the serving host appears. Without it there is no provider
  stratum, so every response fetch asks for full detail.
* ``page_size`` above 200 is rejected with ``400``, not clamped.
* The bulk export endpoint returns one gzipped JSONL file per day, with full
  detail, in a single request. Preferring it turns ~25 paged requests per day
  into one, which keeps a full backfill inside the anonymous rate limit.

If upstream cannot be reached, every function here raises. Nothing in this
module invents a value to carry on with.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import time
from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..models import ModelRow, Question, RawResponse

#: Days to step back when probing for the archive's earliest day.
_PROBE_STEPS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)


class AMTError(RuntimeError):
    """Upstream could not be read. Always fatal: the pipeline must not continue."""


def _is_gateway_404(response: httpx.Response) -> bool:
    """A 404 from the gateway rather than from the API itself.

    The API answers a genuine 404 with a JSON body. The gateway's version is a
    bare text ``404 page not found``, and it is transient.
    """
    if response.status_code != 404:
        return False
    content_type = response.headers.get("content-type", "")
    return "json" not in content_type.lower()


class AMTAuthError(AMTError):
    """Upstream returned 403. A key is required for this request."""


class RateLimiter:
    """Token bucket sized from settings.

    The anonymous limit on list endpoints is 30/min; a key raises it to 120.
    Exceeding it earns a 429, so requests wait for a token rather than racing.
    """

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(max(1, per_minute))
        self.rate = self.capacity / 60.0
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until one token is available, then spend it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = (1.0 - self._tokens) / self.rate
            await asyncio.sleep(deficit)


class AMTClient:
    """Rate-limited, bounded-concurrency reader for the AMT API."""

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.amt_base_url.rstrip("/")
        self._limiter = RateLimiter(self.settings.effective_rate_per_min)
        self._semaphore = asyncio.Semaphore(max(1, self.settings.concurrency))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.request_timeout),
            headers={
                "Accept": "application/json",
                "User-Agent": "antilethe/0.1 (+https://github.com/anti-lethe/anti-lethe)",
                **self.settings.auth_headers,
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> AMTClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying transport if this client created it."""
        if self._owns_client:
            await self._client.aclose()

    # -- transport ----------------------------------------------------------

    async def _request(
        self, url: str, *, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> httpx.Response:
        """One GET, with rate limiting, backoff, and fatal errors on refusal."""
        attempts = max(1, self.settings.max_retries)
        last: Exception | None = None

        for attempt in range(attempts):
            await self._limiter.acquire()
            async with self._semaphore:
                try:
                    response = await self._client.get(
                        url,
                        params=params,
                        timeout=timeout if timeout is not None else self.settings.request_timeout,
                    )
                except httpx.HTTPError as exc:  # transport-level failure
                    last = exc
                    await asyncio.sleep(min(30.0, 2.0**attempt))
                    continue

            if response.status_code == 403:
                raise AMTAuthError(
                    f"{url} returned 403. This request needs an API key: set AMT_KEY "
                    "(or ANTILETHE_AMT_KEY) to a token for the AMT API."
                )
            if response.status_code == 429:
                raise_after = _retry_after(response)
                last = AMTError(f"{url} returned 429")
                await asyncio.sleep(raise_after)
                continue
            if response.status_code >= 500 or _is_gateway_404(response):
                # A real API 404 is a JSON body with a "detail". A bare
                # "404 page not found" is the gateway in front of the API
                # losing the route for a moment; seen intermittently under
                # load, and gone on retry.
                last = AMTError(f"{url} returned {response.status_code}: {response.text[:80]!r}")
                await asyncio.sleep(min(30.0, 2.0**attempt))
                continue
            if response.status_code >= 400:
                raise AMTError(f"{url} returned {response.status_code}: {response.text[:300]}")
            return response

        raise AMTError(f"giving up on {url} after {attempts} attempts: {last}")

    async def _get_json(self, path: str, **params: Any) -> dict[str, Any]:
        """GET a JSON object from a path relative to the API base."""
        response = await self._request(f"{self.base}{path}", params=params or None)
        return _as_object(path, response.json())

    async def _paginate(
        self, path: str, *, timeout: float | None = None, **params: Any
    ) -> list[dict[str, Any]]:
        """Collect every page, following ``next`` verbatim.

        Page URLs are never constructed here: upstream's ``next`` already carries
        the right cursor and query parameters.
        """
        response = await self._request(f"{self.base}{path}", params=params, timeout=timeout)
        page = _as_object(path, response.json())
        rows: list[dict[str, Any]] = list(page.get("results") or [])
        next_url = page.get("next")
        while next_url:
            response = await self._request(str(next_url), timeout=timeout)
            page = _as_object(path, response.json())
            rows.extend(page.get("results") or [])
            next_url = page.get("next")
        return rows

    # -- resources ----------------------------------------------------------

    async def fetch_questions(self) -> list[Question]:
        """The curated question set."""
        rows = await self._paginate(
            "/questions/", enabled="true", page_size=self.settings.page_size
        )
        return [Question.from_api(r) for r in rows]

    async def fetch_models(self, day: date | str | None = None) -> list[ModelRow]:
        """The model catalogue, stamped with the day it was observed.

        Upstream exposes only a "recent" view, so the catalogue is a snapshot:
        each ingest stamps it with the current day, and price history is the
        sequence of those snapshots that differ.
        """
        stamp = _day_str(day) if day is not None else datetime.now(UTC).date().isoformat()
        rows = await self._paginate(
            "/models/recent/", filter="selected", page_size=self.settings.page_size
        )
        return [ModelRow.from_api(r, stamp) for r in rows]

    async def fetch_day(self, day: date | str) -> list[RawResponse]:
        """Every archived answer for one day, with full detail.

        Tries the gzipped bulk export first, falling back to pagination if the
        export is unavailable or arrives truncated.
        """
        key = _day_str(day)
        export_error: AMTError | None = None
        if self.settings.use_bulk_export:
            try:
                return await self._fetch_day_export(key)
            except AMTAuthError:
                raise
            except AMTError as exc:
                export_error = exc
        try:
            return await self._fetch_day_paged(key)
        except AMTError as exc:
            if export_error is None:
                raise
            # Both routes failed. The export's failure is the one worth
            # reading, and it must not be hidden behind the fallback's.
            raise AMTError(f"{exc}; the bulk export had failed first: {export_error}") from exc

    async def _fetch_day_export(self, day: str) -> list[RawResponse]:
        """One day via ``/exports/responses/`` (gzipped JSONL, full detail)."""
        response = await self._request(
            f"{self.base}/exports/responses/",
            params={"day": day},
            timeout=self.settings.bulk_timeout,
        )
        body = response.content
        if not body[:2] == b"\x1f\x8b":
            raise AMTError(f"export for {day} is not gzip ({body[:16]!r})")
        try:
            text = gzip.decompress(body).decode("utf-8")
        except (OSError, EOFError, UnicodeDecodeError) as exc:
            raise AMTError(f"export for {day} did not decompress cleanly: {exc}") from exc
        rows: list[RawResponse] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise AMTError(f"export for {day} contains an unparseable line: {exc}") from exc
            rows.append(RawResponse.from_api(record))
        if not rows:
            raise AMTError(f"export for {day} contained no records")
        return rows

    async def _fetch_day_paged(self, day: str) -> list[RawResponse]:
        """One day via ``/responses/``, which needs ``detail=full`` for turns."""
        rows = await self._paginate(
            "/responses/",
            timeout=self.settings.bulk_timeout,
            day=day,
            detail="full",
            page_size=self.settings.page_size,
        )
        return [RawResponse.from_api(r) for r in rows]

    async def fetch_series(
        self,
        question_slug: str,
        model_id: str,
        *,
        known_days: Collection[str] = (),
        page_size: int | None = None,
    ) -> list[RawResponse]:
        """Archived answers for one (question, model) pair, newest day first.

        One series is a single small request, where a whole day is tens of
        megabytes. Upstream throttles each connection to roughly 25 KB/s, so
        when the goal is depth over time rather than full daily coverage, this
        is the cheap way in by a wide margin.

        Upstream orders a series newest first. Given ``known_days``, paging
        stops at the first page made entirely of days already stored, so a
        daily top-up costs one or two small pages per series instead of the
        whole history. The stop is safe by construction: if the ordering were
        ever not newest-first the condition simply never fires and every page
        is read, which is slower but complete.
        """
        size = page_size or self.settings.page_size
        response = await self._request(
            f"{self.base}/responses/",
            params={
                "question_slug": question_slug,
                "model_id": model_id,
                "detail": "full",
                "page_size": size,
            },
            # A reasoning-heavy model's history is megabytes of encrypted
            # reasoning blobs, which the short list timeout cannot cover.
            timeout=self.settings.bulk_timeout,
        )
        page = _as_object("/responses/", response.json())
        rows: list[RawResponse] = []
        while True:
            results = list(page.get("results") or [])
            rows.extend(RawResponse.from_api(r) for r in results)
            if known_days and results and all(str(r.get("day")) in known_days for r in results):
                break
            next_url = page.get("next")
            if not next_url:
                break
            response = await self._request(str(next_url), timeout=self.settings.bulk_timeout)
            page = _as_object("/responses/", response.json())
        return rows

    async def day_count(self, day: date | str) -> int:
        """How many answers upstream holds for a day, without downloading them."""
        page = await self._get_json("/responses/", day=_day_str(day), page_size=1)
        return int(page.get("count") or 0)

    async def discover_range(self) -> tuple[date, date]:
        """Find the archive's first and last day.

        Walks back from today in exponentially growing steps until a day comes
        back empty, then bisects between that empty day and the last non-empty
        one. Costs about 2*log2(span) requests, and the caller caches it.
        """
        today = datetime.now(UTC).date()

        last: date | None = None
        for back in range(0, 8):
            candidate = today - timedelta(days=back)
            if await self.day_count(candidate) > 0:
                last = candidate
                break
        if last is None:
            raise AMTError("no archived day found within the last 8 days")

        # Exponential walk-back for a known-empty lower bound.
        low: date | None = None
        high = last
        for step in _PROBE_STEPS:
            candidate = last - timedelta(days=step)
            if await self.day_count(candidate) == 0:
                low = candidate
                break
            high = candidate
        if low is None:
            return high, last

        # Bisect: `low` is empty, `high` is non-empty; find the boundary.
        while (high - low).days > 1:
            mid = low + timedelta(days=(high - low).days // 2)
            if await self.day_count(mid) > 0:
                high = mid
            else:
                low = mid
        return high, last


def _as_object(path: str, payload: Any) -> dict[str, Any]:
    """Require a JSON object, so a surprising shape fails loudly."""
    if not isinstance(payload, dict):
        raise AMTError(f"{path} returned {type(payload).__name__}, expected an object")
    return payload


def _retry_after(response: httpx.Response) -> float:
    """Seconds to wait from a ``Retry-After`` header, with a sane fallback."""
    raw = response.headers.get("Retry-After")
    if raw:
        try:
            return max(1.0, min(120.0, float(raw)))
        except ValueError:
            pass
    return 5.0


def _day_str(day: date | str) -> str:
    """Normalise a day to ``YYYY-MM-DD``."""
    return day.isoformat() if isinstance(day, date) else day


def day_range(first: date, last: date) -> Sequence[date]:
    """Every calendar day from ``first`` to ``last`` inclusive."""
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]
