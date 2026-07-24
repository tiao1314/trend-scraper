"""
Signal blending.

Each source produces a raw number on its own scale. This normalises them to
0-100 within the current run and blends them into a single heat score.

Important: scores are RELATIVE TO THE PRODUCTS IN YOUR WATCHLIST, not absolute.
A heat of 90 means "hottest thing on your list right now", not "hottest thing in
the world". Add or remove products and every score shifts. That is the correct
behaviour for a buy-list tool but it will mislead you if you compare scores
across runs with different watchlists.

Weights are deliberately exposed. Tune them - the defaults reflect a
brand-new-stock reseller who cares about demand direction more than current
volume:

  momentum   0.40   where demand is heading
  level      0.20   where demand already is
  scarcity   0.25   thin supply against real demand = pricing power
  editorial  0.15   leading indicator, one quarter ahead
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WEIGHTS = {
    "momentum": 0.40,
    "level": 0.20,
    "scarcity": 0.25,
    "editorial": 0.15,
}


def normalise(values: dict[str, float]) -> dict[str, float]:
    """Min-max scale a mapping to 0-100. Flat input maps to 50 across the board."""
    if not values:
        return {}
    numbers = list(values.values())
    low, high = min(numbers), max(numbers)
    if high - low < 1e-9:
        return {key: 50.0 for key in values}
    return {key: (value - low) / (high - low) * 100.0 for key, value in values.items()}


def scarcity_signal(listings: dict[str, int]) -> dict[str, float]:
    """
    Fewer active listings = scarcer = more pricing power, so this inverts.
    Zero listings is treated as maximum scarcity, which is usually right but
    occasionally means nobody wants the thing - always sanity-check a product
    scoring high on scarcity alone.
    """
    if not listings:
        return {}
    ceiling = max(listings.values()) or 1
    return {key: (1.0 - (count / ceiling)) * 100.0 for key, count in listings.items()}


@dataclass
class Scored:
    product: str
    heat_score: float
    heat_band: int
    momentum: float
    level: float
    listings: int
    median_price: float
    mentions: int
    verdict: str


def band(score: float) -> int:
    if score >= 80:
        return 5
    if score >= 62:
        return 4
    if score >= 42:
        return 3
    if score >= 25:
        return 2
    return 1


def verdict(momentum: float, listings: int, mentions: int) -> str:
    if momentum > 40 and listings < 20:
        return "STRONG BUY - demand climbing, supply thin"
    if momentum > 40:
        return "BUY - demand climbing, supply adequate"
    if momentum > 10 and mentions > 0:
        return "WATCH - early editorial support"
    if momentum < -25:
        return "AVOID - demand falling"
    if listings > 200:
        return "CROWDED - heavy competition, margin will be thin"
    return "HOLD - no clear signal"


def blend(trends: dict[str, dict], ebay: dict[str, dict],
          news: dict[str, dict], weights: dict[str, float] | None = None) -> list[Scored]:
    weights = weights or DEFAULT_WEIGHTS
    products = sorted(set(trends) | set(ebay) | set(news))

    momentum_raw = {p: trends.get(p, {}).get("momentum", 0.0) for p in products}
    level_raw = {p: trends.get(p, {}).get("level", 0.0) for p in products}
    listings_raw = {p: ebay.get(p, {}).get("listings", 0) for p in products}
    mentions_raw = {p: float(news.get(p, {}).get("mentions", 0)) for p in products}

    momentum_n = normalise(momentum_raw)
    level_n = normalise(level_raw)
    scarcity_n = scarcity_signal(listings_raw)
    editorial_n = normalise(mentions_raw)

    scored: list[Scored] = []
    for product in products:
        score = (
            weights["momentum"] * momentum_n.get(product, 0.0)
            + weights["level"] * level_n.get(product, 0.0)
            + weights["scarcity"] * scarcity_n.get(product, 0.0)
            + weights["editorial"] * editorial_n.get(product, 0.0)
        )
        scored.append(Scored(
            product=product,
            heat_score=round(score, 1),
            heat_band=band(score),
            momentum=momentum_raw[product],
            level=level_raw[product],
            listings=listings_raw[product],
            median_price=ebay.get(product, {}).get("median_price", 0.0),
            mentions=int(mentions_raw[product]),
            verdict=verdict(momentum_raw[product], listings_raw[product],
                            int(mentions_raw[product])),
        ))

    scored.sort(key=lambda s: s.heat_score, reverse=True)
    return scored
