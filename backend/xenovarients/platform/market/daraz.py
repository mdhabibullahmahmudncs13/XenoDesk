"""Daraz Bangladesh catalogue search — the free local price and competition source.

Daraz exposes no public market-wide catalogue API: Open Platform is seller-scoped and
requires the seller's own OAuth token. The catalogue endpoint the site's search page
calls is public JSON, so it is read directly here. One request per research run, no
proxy rotation, no individual product-page scraping; results are cached in
``market_snapshots`` for the snapshot's lifetime.

Prices are what Daraz displays, in BDT, including any live discount. That is a retail
price, not a supplier cost, and the payload says so everywhere it is shown.
"""

import re
from typing import Any

import httpx

from xenovarients.platform.market.types import MarketListing

_SEARCH_URL = "https://www.daraz.com.bd/catalog/"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_SOLD = re.compile(r"([\d.,]+)\s*([km])?\s*\+?\s*sold", re.IGNORECASE)


class MarketSourceError(RuntimeError):
    """The source answered with something unusable. Never replaced with a guess."""


def parse_sold(value: str | None) -> int | None:
    """``"484 sold"`` / ``"1.2K sold"`` → an integer, or None when unreadable."""
    if not value:
        return None
    match = _SOLD.search(value)
    if match is None:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        number *= 1000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def _price(value: Any) -> float | None:
    """A positive BDT amount, or None. Zero and nonsense are treated as missing."""
    try:
        amount = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _rating(value: Any) -> float | None:
    try:
        rating = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return rating if 0 < rating <= 5 else None


def _reviews(value: Any) -> int | None:
    try:
        count = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def parse_listings(payload: dict[str, Any]) -> tuple[MarketListing, ...]:
    """Map Daraz's list items to normalised listings, dropping unpriced rows."""
    items = (payload.get("mods") or {}).get("listItems") or []
    listings: list[MarketListing] = []
    for item in items:
        listing_id = str(item.get("itemId") or item.get("nid") or "").strip()
        title = str(item.get("name") or "").strip()
        if not listing_id or not title:
            continue
        sold = parse_sold(item.get("itemSoldCntShow"))
        if sold is None:
            sold = _reviews(item.get("itemSoldCnt"))
        listings.append(
            MarketListing(
                listing_id=listing_id,
                title=title,
                price_bdt=_price(item.get("price")),
                original_price_bdt=_price(item.get("originalPrice")),
                seller_id=str(item.get("sellerId") or "").strip() or None,
                seller_name=str(item.get("sellerName") or "").strip() or None,
                rating=_rating(item.get("ratingScore")),
                reviews=_reviews(item.get("review")),
                units_sold=sold,
                location=str(item.get("location") or "").strip() or None,
                in_stock=bool(item.get("inStock", True)),
                url=f"https://www.daraz.com.bd/products/-i{listing_id}.html",
            )
        )
    return tuple(listings)


async def fetch_listings(
    keyword: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[MarketListing, ...]:
    """One page of Daraz results for the keyword (40 listings)."""
    owns_client = client is None
    client = client or httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    try:
        response = await client.get(
            _SEARCH_URL,
            params={"ajax": "true", "q": keyword},
        )
        if response.status_code != 200:
            raise MarketSourceError(f"Daraz answered HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketSourceError("Daraz returned a page that is not JSON.") from exc
        listings = parse_listings(payload)
        if not listings:
            raise MarketSourceError(f"Daraz returned no listings for “{keyword}”.")
        return listings
    except httpx.HTTPError as exc:
        raise MarketSourceError(
            f"Daraz did not respond ({exc.__class__.__name__})."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()
