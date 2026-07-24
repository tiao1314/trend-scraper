"""
eBay signal, via the official API.

For a reseller this is the single most valuable source on the list, because it
reports what things actually sold for rather than what someone hoped to charge.
It is also fully sanctioned - no scraping, no bot protection, no grey area.

Two APIs matter:

  Browse API  (general availability)
      Active listings: how many are live, and the asking-price spread.
      A thin supply of active listings against high search momentum is the
      classic buy signal.

  Marketplace Insights API (restricted - requires application approval)
      Actual completed sales for the last 90 days. Apply through the developer
      portal; approval typically wants a business justification. If you get it,
      swap SEARCH_PATH for the insights endpoint - the response shape is close
      enough that parse_summary below works with minor edits.

Credentials: create an app at developer.ebay.com, then export
  EBAY_CLIENT_ID and EBAY_CLIENT_SECRET
Production and sandbox use different hosts - set EBAY_ENV=sandbox to test
against fake inventory without touching live data.
"""

from __future__ import annotations

import base64
import logging
import os
import statistics
import time

import requests

log = logging.getLogger(__name__)

HOSTS = {
    "production": "https://api.ebay.com",
    "sandbox": "https://api.sandbox.ebay.com",
}
TOKEN_PATH = "/identity/v1/oauth2/token"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

_token_cache: dict[str, tuple[str, float]] = {}


def _host() -> str:
    return HOSTS[os.getenv("EBAY_ENV", "production")]


def get_token() -> str:
    """Client-credentials OAuth token, cached until shortly before expiry."""
    env = os.getenv("EBAY_ENV", "production")
    cached = _token_cache.get(env)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET. Create an application "
            "at developer.ebay.com to get them."
        )

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        _host() + TOKEN_PATH,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": SCOPE},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    _token_cache[env] = (token, time.time() + float(payload.get("expires_in", 7200)))
    return token


def parse_summary(items: list[dict]) -> dict:
    """Condense a list of item summaries into price and supply statistics."""
    prices: list[float] = []
    for item in items:
        raw = (item.get("price") or {}).get("value")
        if raw is None:
            continue
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            continue

    if not prices:
        return {"listings": 0, "median_price": 0.0, "min_price": 0.0, "max_price": 0.0}

    return {
        "listings": len(prices),
        "median_price": round(statistics.median(prices), 2),
        "min_price": round(min(prices), 2),
        "max_price": round(max(prices), 2),
    }


def collect(terms: list[str], marketplace: str = "EBAY_GB",
            limit: int = 100, condition_new_only: bool = True) -> dict[str, dict]:
    """
    Return {term: {listings, median_price, min_price, max_price}}.

    marketplace: EBAY_GB, EBAY_US, EBAY_DE, EBAY_IE routes to EBAY_GB (eBay
    has no separate Irish marketplace ID - Irish sellers list on EBAY_IE
    domain but the API marketplace is EBAY_IE only for some calls; EBAY_GB is
    the safe default for Ireland).

    condition_new_only: filter to new items, since you are reselling brand new.
    """
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
        "Content-Type": "application/json",
    }

    results: dict[str, dict] = {}
    for term in terms:
        params = {"q": term, "limit": str(min(limit, 200))}
        if condition_new_only:
            params["filter"] = "conditions:{NEW}"

        try:
            resp = requests.get(_host() + SEARCH_PATH, headers=headers,
                                params=params, timeout=20)
            if resp.status_code == 429:
                log.warning("eBay rate limit on '%s' - sleeping 30s", term)
                time.sleep(30)
                resp = requests.get(_host() + SEARCH_PATH, headers=headers,
                                    params=params, timeout=20)
            resp.raise_for_status()
            summary = parse_summary(resp.json().get("itemSummaries", []))
        except requests.RequestException as exc:
            log.warning("eBay lookup failed for '%s': %s", term, exc)
            summary = {"listings": 0, "median_price": 0.0,
                       "min_price": 0.0, "max_price": 0.0}

        results[term] = summary
        log.info("ebay   %-45s listings=%3d median=%.2f",
                 term, summary["listings"], summary["median_price"])
        time.sleep(0.3)  # stay well inside the default 5000 calls/day quota

    return results
