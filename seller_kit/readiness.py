"""Seller agent-readiness for a new shop's listing pages (Lane C, #412 item 3c).

summarize(cfg, fetch=None, now=None) -> {"line", "listings": [{"sku", "url", "status", "summary", "blocks", "warnings",
    "checked_at", "origin"}]}

Each listing page is read once, live, with data.readiness.check_listing (public addresses only, 2 MB cap). At most MAX_PAGES
pages per request, all within BUDGET_S; the rest say so. A page on a local, private or placeholder address (localhost, 127.0.0.1,
10.x, *.local, example.com, *.test and the like) is never fetched, so a hosted run can never be pointed at the machine it runs on.
No page URL at all reads "Readiness: not checked (no listing page given)". A page that cannot be read is "unreadable", never
"ready". Readiness is advice: it never stops a shop from being written.
"""
from __future__ import annotations

import ipaddress
import re
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_PAGES = 3
BUDGET_S = 25.0
FETCH = None  # tests set a fake page fetch here; None means data.claim_check.fetch.guarded_get
NO_PAGE = "Readiness: not checked (no listing page given)"
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".test", ".example", ".invalid")
PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net")
NUMERIC_HOST = re.compile(r"[0-9.]+|0x[0-9a-f.]+", re.I)  # 2130706433, 1.2.3, 0x7f.1: a number is not a public shop name


def not_public(url: str) -> bool:
    """True when the page is not a public address a shop could really serve: nothing is fetched for it."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return True
    if not host or host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        return True
    if host in PLACEHOLDER_HOSTS or host.endswith(tuple("." + h for h in PLACEHOLDER_HOSTS)):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return bool(NUMERIC_HOST.fullmatch(host))


def _skipped(sku: str, url, why: str) -> dict:
    return {"sku": sku, "url": url or None, "status": "not_checked", "summary": f"NOT CHECKED: {why}", "blocks": 0, "warnings": 0}


def _row(sku: str, url: str, r: dict) -> dict:
    findings = r.get("findings") or []
    return {"sku": sku, "url": url, "status": r.get("status", "unreadable"), "summary": r.get("summary", ""),
            "blocks": sum(f.get("severity") == "blocks" for f in findings), "warnings": sum(f.get("severity") == "warns" for f in findings),
            "checked_at": r.get("checked_at"), "origin": r.get("origin", "LIVE")}


def _line(rows: list[dict]) -> str:
    if not any(r["url"] for r in rows):
        return NO_PAGE
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    if set(counts) == {"not_checked"}:
        return "Readiness: not checked (no public listing page to read)"
    parts = [f"{counts[s]} {s.replace('_', ' ')}" for s in ("ready", "warns", "blocks", "unreadable", "not_checked") if counts.get(s)]
    return "Readiness (LIVE page reads): " + ", ".join(parts)


def summarize(cfg: dict, fetch=None, now: datetime | None = None) -> dict:
    from data.readiness import check_listing
    fetch = fetch or FETCH
    now = now or datetime.now(timezone.utc)
    listings = cfg.get("listings") if isinstance(cfg, dict) else None
    rows: list[dict | None] = []
    todo: list[tuple[int, str, str]] = []
    for sku, ls in (listings.items() if isinstance(listings, dict) else []):
        url = ls.get("listing_url") if isinstance(ls, dict) else None
        url = url.strip() if isinstance(url, str) else ""
        if not url:
            rows.append(_skipped(sku, None, "no listing page given"))
        elif not_public(url):
            rows.append(_skipped(sku, url, "the listing page is a local, private or placeholder address, so it was not fetched"))
        elif len(todo) >= MAX_PAGES:
            rows.append(_skipped(sku, url, f"only {MAX_PAGES} pages are read per request"))
        else:
            todo.append((len(rows), sku, url))
            rows.append(None)
    if todo:
        pool = ThreadPoolExecutor(max_workers=len(todo))
        futures = {pool.submit(check_listing, url, fetch, now): (i, sku, url) for i, sku, url in todo}
        done, _ = wait(futures, timeout=BUDGET_S)
        pool.shutdown(wait=False, cancel_futures=True)
        for f, (i, sku, url) in futures.items():
            try:
                rows[i] = _row(sku, url, f.result()) if f in done else _skipped(sku, url, f"the page took longer than {BUDGET_S:g} s")
            except Exception as e:  # nothing is known about the page: unreadable, never ready
                rows[i] = _row(sku, url, {"status": "unreadable", "summary": f"UNREADABLE: could not check ({type(e).__name__})"})
    out = [r for r in rows if r]
    return {"line": _line(out), "listings": out}
