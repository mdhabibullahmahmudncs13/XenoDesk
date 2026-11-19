"""Normalised records for Market Intelligence.

Both providers are free and public: Google Trends and Daraz Bangladesh's catalogue
endpoint. Nothing here invents a value — a field the source did not return is ``None``,
and the metrics layer reports it as unavailable instead of filling it in.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TrendPoint:
    """One bucket of Google's 0-100 relative interest, keyed by month."""

    period: str
    index: float


@dataclass(frozen=True)
class RegionInterest:
    region: str
    index: float


@dataclass(frozen=True)
class RelatedQuery:
    query: str
    kind: str
    score: int = 0


@dataclass(frozen=True)
class TrendSeries:
    points: tuple[TrendPoint, ...] = ()
    regions: tuple[RegionInterest, ...] = ()
    related: tuple[RelatedQuery, ...] = ()
    fetched_at: datetime | None = None
    source_url: str = ""


@dataclass(frozen=True)
class MarketListing:
    """One marketplace listing as Daraz returned it."""

    listing_id: str
    title: str
    price_bdt: float | None = None
    original_price_bdt: float | None = None
    seller_id: str | None = None
    seller_name: str | None = None
    rating: float | None = None
    reviews: int | None = None
    units_sold: int | None = None
    location: str | None = None
    in_stock: bool = True
    url: str | None = None
