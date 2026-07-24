# Luxury Resale Trend Scraper

Collects demand signals for a watchlist of products, blends them into a single
heat score, and ranks them into a buy list. Seeded with the 73 bags and shoes
from `trending_luxury_bags_shoes_2026.xlsx`.

## Install

```bash
pip install -r requirements.txt
```

## Verify it works before wiring up any keys

```bash
python test_offline.py        # 27 assertions, no network
python run.py --mock          # full pipeline on fixture data
```

`--mock` runs collection, scoring, console output and xlsx export end to end
without a single network call. If that produces a sensible table, your logic is
sound and anything that breaks later is a credentials or connectivity problem,
not a code problem.

## Test the HTML scraping layer

```bash
python run.py --scrape-demo books_sandbox
python run.py --scrape-demo quotes_sandbox
```

`books.toscrape.com` and `quotes.toscrape.com` are maintained by the Scrapy team
specifically as scraping practice targets. They permit automated access and are
built like a real product catalogue — pagination, prices, stock status — so
they exercise the same code paths a live catalogue would. Get your selectors and
pagination right here first.

## Live run

```bash
export EBAY_CLIENT_ID=your_id
export EBAY_CLIENT_SECRET=your_secret
python run.py --watchlist watchlist.csv --geo IE --marketplace EBAY_GB
```

Add `--no-ebay` to run on Google Trends and RSS alone (no credentials needed).

## Find models you aren't tracking yet

```bash
python run.py --discover "Coach bag" --geo IE
python run.py --discover "designer loafers" --geo GB
```

Returns Google's "rising" related queries — the fastest way to catch a model
name climbing before it reaches the fashion press.

## Files

| File | Purpose |
|---|---|
| `run.py` | CLI entry point |
| `fetcher.py` | HTTP layer: robots.txt, rate limiting, caching, backoff |
| `scoring.py` | Signal normalisation and heat scoring |
| `sources/google_trends.py` | Search demand and momentum |
| `sources/ebay_api.py` | Official eBay API — listings and price stats |
| `sources/rss_news.py` | Editorial mention counts from press RSS |
| `sources/generic_html.py` | Config-driven HTML scraper |
| `watchlist.csv` | 73 products, editable |
| `test_offline.py` | Offline test suite |

## How the score works

| Signal | Weight | Meaning |
|---|---|---|
| Momentum | 0.40 | Last 4 weeks vs prior 12. Where demand is heading. |
| Level | 0.20 | Current search volume. Where demand already is. |
| Scarcity | 0.25 | Inverted listing count. Thin supply = pricing power. |
| Editorial | 0.15 | Press mentions. Runs ~1 quarter ahead of search. |

Weights live in `scoring.DEFAULT_WEIGHTS` — tune them.

**Scores are relative to your watchlist, not absolute.** A heat of 90 means
"hottest thing on your list", not "hottest thing in the world". Change the
watchlist and every score shifts. Don't compare scores across runs with
different watchlists.

## Sources and why these ones

**Google Trends** — pytrends is an unofficial client for a public endpoint.
Rate-limited aggressively; the code batches 5 terms per request (Google's hard
limit) with an 8-second pause. Expect the odd 429.

**eBay API** — the best source on this list for a reseller, because it reports
what things actually sold for. Free, official, no bot protection. The Browse
API is generally available. Marketplace Insights (90 days of completed sales)
needs an approval application — worth submitting.

**RSS** — feeds exist to be read by software, so there's no ambiguity here.
Fashion press runs roughly a quarter ahead of search volume, which makes this
your leading indicator.

## On the targets that aren't included

StockX, GOAT, Farfetch, Mytheresa and TikTok all serve their catalogues from
JavaScript against internal JSON APIs, sitting behind Cloudflare or PerimeterX.
`requests` + BeautifulSoup gets you a 403 or an empty shell — the fetcher will
tell you so explicitly rather than retrying pointlessly. Getting past that needs
a headless browser plus residential proxies plus fingerprint evasion, which is
circumvention tooling aimed at a site actively refusing automated clients. That's
a terms-of-service breach, and as a registered trading business it's legal
exposure you don't need for data you can get legitimately elsewhere.

Where a site has an API, use it. For StockX-grade resale pricing, licensed data
resellers exist and sell exactly this.

The `generic_html` module is target-agnostic. If you have permission from a
site, add a `SiteProfile` and it will work.

## Housekeeping

- Set a real contact address in `USER_AGENT` in `run.py`. Sites that can see
  who you are and how to reach you are far more tolerant than sites facing an
  anonymous scraper.
- Responses cache to `.cache/` for 6 hours. During development this is what
  keeps you from hammering a server while debugging selectors.
- Default delay is 2s per host, raised automatically if robots.txt declares a
  longer `Crawl-delay`.
- `respect_robots=True` by default, mirroring Scrapy's `ROBOTSTXT_OBEY`.
