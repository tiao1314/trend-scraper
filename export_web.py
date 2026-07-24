#!/usr/bin/env python3
"""
Export a scored run to docs/data.json for the website.

  python export_web.py --mock                 # fixture data (no network/keys)
  python export_web.py --auto-discover --geo IE   # live, grows the watchlist

The website (docs/index.html) is static - it just reads the JSON this writes,
so it works on GitHub Pages. Re-run this and commit docs/data.json to refresh.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import scoring

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"


def watchlist_lookup() -> dict[str, dict]:
    """search_term -> {gender, category, brand} from watchlist.csv."""
    path = ROOT / "watchlist.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
        term = (row.get("search_term") or "").strip()
        if term:
            out[term] = {
                "gender": (row.get("gender") or "").strip() or "?",
                "category": (row.get("category") or "").strip(),
                "brand": (row.get("brand") or "").strip(),
            }
    return out


def build_rows(mode: str, geo: str, auto_discover: bool) -> list[scoring.Scored]:
    import run
    if mode == "mock":
        trends, ebay, news = run.load_fixtures()
    else:
        wl = ROOT / "watchlist.csv"
        terms = run.load_watchlist(wl)
        if auto_discover:
            from sources import autodiscover
            new_rows = autodiscover.expand(terms, geo=geo)
            if run.append_watchlist(wl, new_rows):
                terms = run.load_watchlist(wl)
        import os
        from sources import google_trends
        trends = google_trends.collect(terms, geo=geo)

        # eBay needs API keys. If they are not set, skip it (empty columns)
        # rather than crash - real Trends/press data still flows.
        ebay = {}
        if os.getenv("EBAY_CLIENT_ID") and os.getenv("EBAY_CLIENT_SECRET"):
            from sources import ebay_api
            ebay = ebay_api.collect(terms)
        else:
            print("NOTE: no EBAY_CLIENT_ID/SECRET set - skipping eBay signal "
                  "(listings/price will be blank). Real Trends + press still used.")

        from sources import rss_news
        news = rss_news.collect(terms)
    return scoring.blend(trends, ebay, news)


def main() -> int:
    ap = argparse.ArgumentParser(description="Export scored data to docs/data.json")
    ap.add_argument("--mock", action="store_true", help="fixture data, no network")
    ap.add_argument("--auto-discover", action="store_true")
    ap.add_argument("--geo", default="")
    args = ap.parse_args()

    mode = "mock" if args.mock else "live"
    rows = build_rows(mode, args.geo, args.auto_discover)
    meta = watchlist_lookup()

    items = []
    for i, r in enumerate(rows, start=1):
        info = meta.get(r.product, {})
        items.append({
            "rank": i,
            "product": r.product,
            "heat_score": r.heat_score,
            "band": r.heat_band,
            "momentum": r.momentum,
            "level": r.level,
            "listings": r.listings,
            "median_price": r.median_price,
            "mentions": r.mentions,
            "verdict": r.verdict,
            "gender": info.get("gender", "?"),
            "category": info.get("category", ""),
            "brand": info.get("brand", ""),
        })

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode,
        "geo": args.geo or "worldwide",
        "count": len(items),
        "items": items,
    }

    DOCS.mkdir(exist_ok=True)
    out = DOCS / "data.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(items)} rows, mode={mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
