"""Cursor-based pagination.

Offset pagination is not used on the large tables — inserts would shift rows between pages.
The cursor encodes the last seen sort key so the next page starts exactly where the last
one ended.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

MAX_LIMIT = 100
DEFAULT_LIMIT = 25


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True)
class Cursor:
    """Opaque cursor over a (sort_column, sort_id) pair."""

    value: str
    id: str


def encode_cursor(value: Any, row_id: Any) -> str:
    raw = json.dumps({"v": str(value), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw)
        return Cursor(value=str(data["v"]), id=str(data["i"]))
    except (binascii.Error, ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor") from exc


def paginate_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return min(limit, MAX_LIMIT)
