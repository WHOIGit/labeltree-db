"""Conventions shared by every read endpoint (spec: api-conventions).

- errors: {status, error, detail}
- ?rev: latest when omitted (adds X-Tree-Revision); 404 outside 1..latest
- ETag: SHA-256 of the response body; If-None-Match -> 304
- pagination: ?limit=&offset= with `count`
"""

import hashlib
import json

from django.http import HttpResponse

from core.changesets import latest_rev
from core.models import Tree


class APIError(Exception):
    def __init__(self, status: int, error: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.error = error
        self.detail = detail

    def body(self) -> dict:
        return {"status": self.status, "error": self.error, "detail": self.detail}


def not_found(detail: str) -> APIError:
    return APIError(404, "not_found", detail)


def bad_parameter(detail: str) -> APIError:
    return APIError(400, "bad_parameter", detail)


def error_response(error: APIError) -> HttpResponse:
    return HttpResponse(
        json.dumps(error.body()), status=error.status, content_type="application/json"
    )


# --- Revisions ------------------------------------------------------------------


def get_tree(tree_id: str) -> Tree:
    try:
        return Tree.objects.get(pk=tree_id)
    except Tree.DoesNotExist:
        raise not_found(f"Tree {tree_id} does not exist.") from None


def resolve_rev(tree_id: str, rev: int | None) -> tuple[int, int, bool]:
    """Returns (rev, latest, is_latest_by_default). 404 if rev is outside 1..latest."""
    latest = latest_rev(tree_id)
    if rev is None:
        return latest, latest, True
    if not 1 <= rev <= latest:
        raise not_found(f"Tree {tree_id} has no revision {rev}; latest is {latest}.")
    return rev, latest, False


def parse_depth(depth: str) -> int | None:
    """`all` -> None (unlimited); otherwise a non-negative integer."""
    if depth == "all":
        return None
    try:
        value = int(depth)
    except ValueError:
        value = -1
    if value < 0:
        raise bad_parameter(f"depth must be `all` or a non-negative integer, not {depth!r}.")
    return value


# --- Responses -------------------------------------------------------------------


def drop_empty(node: dict) -> dict:
    """?dropempty=true: omit fields that are null, empty strings or empty lists."""
    return {k: v for k, v in node.items() if v is not None and v != "" and v != []}


def _etag_matches(request, etag: str) -> bool:
    header = request.headers.get("If-None-Match", "")
    candidates = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    return etag in candidates or "*" in candidates


def respond(
    request,
    data,
    *,
    rev: int | None = None,
    content_type: str = "application/json",
) -> HttpResponse:
    """Serialise a read response with an ETag, honouring If-None-Match.

    `rev` is set when the response was built from the latest revision because
    ?rev was omitted, and becomes the X-Tree-Revision header.
    """
    if isinstance(data, (bytes, str)):
        body = data.encode() if isinstance(data, str) else data
    else:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    if _etag_matches(request, etag):
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(body, content_type=content_type)
    response["ETag"] = etag
    if rev is not None:
        response["X-Tree-Revision"] = str(rev)
    return response


# --- Pagination ---------------------------------------------------------------------


def paginate(items, limit: int | None, offset: int, *, default: int = 100, maximum: int = 1000):
    """Slice a queryset or list. Returns (page, count)."""
    limit = default if limit is None else limit
    if not 1 <= limit <= maximum:
        raise bad_parameter(f"limit must be between 1 and {maximum}.")
    if offset < 0:
        raise bad_parameter("offset must not be negative.")
    count = items.count() if hasattr(items, "count") and not isinstance(items, list) else len(items)
    return items[offset : offset + limit], count
