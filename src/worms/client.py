"""HTTP client for the WoRMS REST API (https://www.marinespecies.org/rest).

Every WoRMS call in the service goes through `WormsClient`. It has a 10 s
timeout and retries transient failures (timeouts, connection errors, 5xx),
waiting `backoff` seconds before each retry:

- BACKOFF (1, 2 s) for the lookup endpoints, where a user waits on the answer;
- JOB_BACKOFF (1, 2, 5, 12 s) for WoRMS jobs started through the API;
- SCHEDULED_BACKOFF (10 s to 2 min) for jobs started by the management command,
  which can ride out a WoRMS outage of a few minutes.

`on_wait(aphia_id, attempt, retries, seconds)` is called before each wait, so a
job can show its retries. A failure that persists is raised as `WormsError`
with a classified `reason`:

- `worms_unreachable`: timeout or connection error
- `worms_rate_limited`: HTTP 429
- `worms_error`: any other error response

On HTTP 429 the client waits out `Retry-After` (default 30 s) and retries, or,
with `raise_rate_limited`, raises `RateLimited` at once, so a job can pause as a
whole instead of one request at a time.

WoRMS answers `204 No Content` for an unknown AphiaID or a name with no match;
the client returns None (or []) for those.
"""

import time

import httpx

BASE_URL = "https://www.marinespecies.org/rest"
TIMEOUT = 10.0
# Seconds to wait before each retry; the number of retries is their count.
BACKOFF = (1.0, 2.0)
JOB_BACKOFF = (1.0, 2.0, 5.0, 12.0)
SCHEDULED_BACKOFF = (10.0, 30.0, 60.0, 120.0)
RETRIES = len(BACKOFF)
RETRY_AFTER_DEFAULT = 30.0
# AphiaRecordsByName returns at most this many records per page.
SEARCH_PAGE = 50

# Record fields kept in the cache; the rest (citation, habitat flags, ...) is dropped.
RECORD_FIELDS = (
    "AphiaID", "url", "scientificname", "authority", "status", "unacceptreason", "rank",
    "valid_AphiaID", "valid_name", "modified",
)  # fmt: skip


class WormsError(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class RateLimited(WormsError):
    """HTTP 429, raised at once when the client is told to (`raise_rate_limited`)."""

    def __init__(self, detail: str, retry_after: float):
        super().__init__("worms_rate_limited", detail)
        self.retry_after = retry_after


def normalise_record(raw: dict) -> dict:
    return {k: raw.get(k) for k in RECORD_FIELDS}


def normalise_lineage(nested: dict | None) -> list[dict]:
    """AphiaClassificationByAphiaID's nested {.., child: {..}} -> a list, top level first."""
    lineage = []
    node = nested
    while node:
        lineage.append({k: node.get(k) for k in ("AphiaID", "rank", "scientificname")})
        node = node.get("child")
    return lineage


class WormsClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
        backoff: tuple[float, ...] = BACKOFF,
        on_wait=None,
        raise_rate_limited: bool = False,
    ):
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=TIMEOUT,
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._sleep = sleep
        self._backoff = backoff
        self._on_wait = on_wait
        self._raise_rate_limited = raise_rate_limited

    def close(self):
        self._http.close()

    def _get(self, path: str, params: dict | None = None, aphia_id: int | None = None):
        """GET a WoRMS path; returns the decoded JSON, or None for 204. `aphia_id` is
        passed to `on_wait`."""
        retries = len(self._backoff)
        for attempt in range(retries + 1):
            last = attempt == retries
            backoff = 0.0 if last else self._backoff[attempt]
            try:
                response = self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                error = WormsError("worms_unreachable", f"Timed out requesting {path}: {exc}")
                wait = backoff
            except httpx.TransportError as exc:
                error = WormsError("worms_unreachable", f"Can't connect for {path}: {exc}")
                wait = backoff
            else:
                if response.status_code == 204:
                    return None
                if response.is_success:
                    return response.json()
                if response.status_code == 429:
                    detail = f"HTTP 429 requesting {path}."
                    if self._raise_rate_limited:
                        raise RateLimited(detail, _retry_after(response))
                    error = WormsError("worms_rate_limited", detail)
                    wait = _retry_after(response)
                elif response.status_code >= 500:
                    error = WormsError(
                        "worms_error", f"HTTP {response.status_code} requesting {path}."
                    )
                    wait = backoff
                else:
                    raise WormsError(
                        "worms_error", f"HTTP {response.status_code} requesting {path}."
                    )
            if last:
                raise error
            if self._on_wait:
                self._on_wait(aphia_id, attempt + 1, retries, wait)
            self._sleep(wait)
        raise AssertionError("unreachable")

    def record(self, aphia_id: int) -> dict | None:
        raw = self._get(f"/AphiaRecordByAphiaID/{aphia_id}", aphia_id=aphia_id)
        return normalise_record(raw) if raw else None

    def lineage(self, aphia_id: int) -> list[dict] | None:
        nested = self._get(f"/AphiaClassificationByAphiaID/{aphia_id}", aphia_id=aphia_id)
        return normalise_lineage(nested) if nested else None

    def full_record(self, aphia_id: int) -> dict | None:
        """The record with its lineage, as stored in the cache; None if WoRMS has no record."""
        record = self.record(aphia_id)
        if record is None:
            return None
        return {**record, "lineage": self.lineage(aphia_id) or []}

    def search(self, name: str, limit: int = 20) -> list[dict]:
        """Records whose name matches `name` (WoRMS `like` match), at most `limit`."""
        records = []
        while len(records) < limit:
            page = self._get(
                f"/AphiaRecordsByName/{name}",
                {"like": "true", "marine_only": "false", "offset": len(records) + 1},
            )
            if not page:
                break
            records += [normalise_record(r) for r in page]
            if len(page) < SEARCH_PAGE:
                break
        return records[:limit]


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("Retry-After", RETRY_AFTER_DEFAULT))
    except ValueError:
        return RETRY_AFTER_DEFAULT
