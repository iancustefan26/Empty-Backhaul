"""Paginated scraper for the user's own 123cargo.eu session — Frigo loads.

What this does
--------------
Paginates the authenticated /api2/searchloads endpoint from the user's
own browser session (cookies provided in a local file), filters loads
where `temperatureControlled == "1"` (the platform's "Frigo" / cold-
chain flag), and writes a normalised dataset to disk that the admin
API can later pull into the dispatcher's workspace.

Sourcing
--------
This is functionally identical to the user pressing "Next page" in
their browser 180-ish times. The cookies in the input file are the
user's own session — no scraping of someone else's account, no auth
bypass. 123cargo.eu's Terms of Service may still prohibit programmatic
access; that's between the user and 123cargo.

Output
------
  backend/data/123cargo/frigo_loads.json
      [{
        "id":                 "BM-181841210",
        "source_city":        "Oradea",
        "source_lat":          47.054233,
        "source_lng":          21.939289,
        "destination_city":   "Timisoara",
        "destination_lat":     45.75372,
        "destination_lng":     21.22571,
        "weight_kg":          1000,
        "price_eur":          200.0,           # converted from RON @ 5 RON=1€
        "loading_date":       "21-05-2026",
        "loading_interval_days": 0,
        "route_distance_km":  171,
        "raw_source":         "Oradea, Bihor",
        "raw_destination":    "Timişoara, Timiş",
        "published":          "20-05-2026 11:38:18"
      }, …]

Cookies file format
-------------------
  backend/data/123cargo/cookies.txt    (gitignored — never committed)
    A single line with the full `Cookie:` header value from the
    user's browser DevTools (no `Cookie: ` prefix).

Usage
-----
  python -m scripts.scrape_123cargo --max-results 9000 --delay 1.0
  python -m scripts.scrape_123cargo --max-pages 5 --delay 0.5   # quick sample
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data" / "123cargo"
COOKIES_FILE = DATA_DIR / "cookies.txt"
RAW_DIR = DATA_DIR / "raw"
OUT_FILE = DATA_DIR / "frigo_loads.json"

API_URL = "https://www.123cargo.eu/ro-md/api2/searchloads"
PAGE_SIZE = 50
RON_PER_EUR = 5.0      # rough; the dispatcher only cares about ballpark


def _clean_city(raw: str) -> str:
    """'Timişoara, Timiş' → 'Timisoara' (strip diacritics + drop county)."""
    base = raw.split(",")[0].strip()
    nfkd = unicodedata.normalize("NFKD", base)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _build_request(offset: int, cookies: str, base_date: str) -> urllib.request.Request:
    body = json.dumps({
        "source": [{"country": "RO", "lat": 46, "lng": 25}],
        "destination": [{"country": "RO", "lat": 46, "lng": 25}],
        "extendedRange": 0,
        "loadingDate": base_date,
        "loadingInterval": 9,
        "requiredTruck": [],
        "spotlightOnly": False,
        "_errorNames": {},
    }).encode("utf-8")
    return urllib.request.Request(
        url=f"{API_URL}?limit={PAGE_SIZE}&offset={offset}",
        data=body, method="POST",
        headers={
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "cookie": cookies,
            "origin": "https://www.123cargo.eu",
            "referer": "https://www.123cargo.eu/ro-md/freightexchange/searchload",
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
            ),
        },
    )


def _fetch_page(offset: int, cookies: str, base_date: str) -> dict:
    req = _build_request(offset, cookies, base_date)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _normalise_load(raw: dict) -> dict | None:
    """Map a 123cargo entry → our compact dataset format. Returns None
    if any required field is missing."""
    try:
        src = raw["source"]
        dst = raw["destination"]
        price_eur = 0.0
        if isinstance(raw.get("offeredPrice"), dict):
            p = raw["offeredPrice"]
            try:
                v = float(p.get("price", 0))
                cur = (p.get("currency") or "RON").upper()
                price_eur = v / RON_PER_EUR if cur == "RON" else v
            except (TypeError, ValueError):
                price_eur = 0.0

        return {
            "id":                     raw["id"],
            "source_city":            _clean_city(src["name"]),
            "source_lat":             float(src["lat"]),
            "source_lng":             float(src["lng"]),
            "destination_city":       _clean_city(dst["name"]),
            "destination_lat":        float(dst["lat"]),
            "destination_lng":        float(dst["lng"]),
            "weight_kg":              int(raw.get("weight") or 0),
            "price_eur":              round(price_eur, 2),
            "loading_date":           raw.get("loadingDate", ""),
            "loading_interval_days":  int(raw.get("loadingInterval") or 0),
            "route_distance_km":      int(raw.get("routeDistance") or 0),
            "raw_source":             src["name"],
            "raw_destination":        dst["name"],
            "published":              raw.get("published", ""),
        }
    except (KeyError, TypeError, ValueError):
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-results", type=int, default=9000,
                   help="Cap on TOTAL loads to fetch across all pages")
    p.add_argument("--max-pages", type=int, default=None,
                   help="Hard cap on page count (debug; overrides max-results)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="Seconds to sleep between requests (default 1.0)")
    p.add_argument("--loading-date", default=None,
                   help="DD-MM-YYYY base date for the search (default: today)")
    p.add_argument("--cookies-file", default=str(COOKIES_FILE),
                   help="Path to the single-line cookies file (gitignored)")
    args = p.parse_args()

    cookies_path = Path(args.cookies_file)
    if not cookies_path.exists():
        print(f"[scrape] Cookies file not found at {cookies_path}", file=sys.stderr)
        print(f"[scrape] Paste your Cookie header value (one line, no 'Cookie: '"
              f" prefix) into that file and re-run.", file=sys.stderr)
        return 2
    cookies = cookies_path.read_text(encoding="utf-8").strip()
    if not cookies or "PHPSESSID=" not in cookies:
        print(f"[scrape] Cookies file looks empty or missing PHPSESSID.",
              file=sys.stderr)
        return 2

    base_date = args.loading_date or datetime.now(timezone.utc).strftime("%d-%m-%Y")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    all_loads: list[dict] = []
    frigo_loads: list[dict] = []
    offset = 0
    total_available: int | None = None
    page = 0
    started = time.perf_counter()

    while True:
        if args.max_pages is not None and page >= args.max_pages:
            print(f"[scrape] hit --max-pages={args.max_pages}", file=sys.stderr)
            break
        if len(all_loads) >= args.max_results:
            print(f"[scrape] hit --max-results={args.max_results}", file=sys.stderr)
            break
        try:
            data = _fetch_page(offset, cookies, base_date)
        except urllib.error.HTTPError as e:
            print(f"[scrape] HTTP {e.code} at offset {offset}; aborting",
                  file=sys.stderr)
            print(f"         body: {e.read()[:300]!r}", file=sys.stderr)
            break
        except urllib.error.URLError as e:
            print(f"[scrape] network error at offset {offset}: {e}", file=sys.stderr)
            break

        if data.get("resultCode") != 0:
            print(f"[scrape] resultCode={data.get('resultCode')} at offset {offset}; "
                  f"aborting", file=sys.stderr)
            break

        if total_available is None:
            total_available = int(data.get("availableResults") or 0)
            print(f"[scrape] availableResults: {total_available}", file=sys.stderr)

        # Save raw response in case we need to re-process
        (RAW_DIR / f"page_{offset:06d}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        loads = list(data.get("response", {}).values())
        if not loads:
            print(f"[scrape] empty page at offset {offset}; done", file=sys.stderr)
            break

        for raw in loads:
            all_loads.append(raw)
            if str(raw.get("temperatureControlled")) == "1":
                norm = _normalise_load(raw)
                if norm:
                    frigo_loads.append(norm)

        page += 1
        elapsed = time.perf_counter() - started
        pct = (offset + PAGE_SIZE) / total_available * 100 if total_available else 0
        print(f"[scrape] page {page:4} offset {offset:6} "
              f"({pct:5.1f}%)  scanned {len(all_loads):5}  "
              f"frigo {len(frigo_loads):4}  elapsed {elapsed:5.0f}s",
              file=sys.stderr)

        offset += PAGE_SIZE
        if total_available is not None and offset >= total_available:
            print(f"[scrape] reached availableResults", file=sys.stderr)
            break

        # Polite rate-limit with jitter
        time.sleep(args.delay * (0.9 + 0.2 * random.random()))

    # De-duplicate by id (paginated APIs sometimes return the same row twice
    # when the underlying dataset shifts mid-pagination).
    seen: set[str] = set()
    deduped: list[dict] = []
    for f in frigo_loads:
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        deduped.append(f)

    out_payload = {
        "scraped_at_utc":   datetime.now(timezone.utc).isoformat(),
        "base_search_date": base_date,
        "total_scanned":    len(all_loads),
        "total_available":  total_available,
        "frigo_count":      len(deduped),
        "loads":            deduped,
    }
    OUT_FILE.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\n[scrape] DONE — {len(deduped)} Frigo loads -> {OUT_FILE.relative_to(BACKEND_DIR.parent)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
