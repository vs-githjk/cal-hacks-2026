"""Bright Data discovery: find listing URLs for a SKU through the Google Shopping scraper (night run 2 T16, stretch).

discover() returns LEADS, not bids and not prices. A lead is a page Bright Data found for a keyword, labelled "found by
Bright Data, not a seller agent". It carries no seller id and no price: the discovery scraper's output fields are url,
country, input, warning and error (VERIFIED against docs.brightdata.com/scrapers/gd_ltppk50q18kdw67omz.json at 05:50),
so only url and an optional title are mapped. To price a lead, hand its url to brightdata.observations(urls=[...]).

Every lead is untrusted web text. Titles are length-capped here, but a lead must still go through Bazaar Shield before it
reaches any agent. Only http and https urls are kept.

It shares everything with brightdata.py by import (key, per-process call budget, 429 cooldown, status, last_error, read
timeout), so a discovery call counts against BRIGHT_DATA_MAX_CALLS, and a 429 here also stops price re-checks for 5 minutes.
The call is the sync /scrape endpoint with type=discover_new and discover_by=keyword (the docs say /scrape takes the same
query and body as /trigger). The request body is NOT confirmed by a live call: no keyed smoke has been run for discovery.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import httpx

from data.baselines import brightdata as bd

DATASET_ID = "gd_ltppk50q18kdw67omz"  # Google Shopping, discover_by keyword
LABEL = "found by Bright Data, not a seller agent"
COUNTRY = "US"
DEFAULT_LIMIT = 10  # leads per keyword: about one credit per record, so this is also the cost cap
MAX_TITLE = 200


def _store(url: str) -> str | None:
    """A known retailer's short name, else the bare host. None when the url is not plain http(s) with a host."""
    try:
        u = httpx.URL(url)
        raw_host = u.host  # decodes punycode lazily: a bad IDN host raises here (idna errors are ValueErrors)
    except (httpx.InvalidURL, ValueError):
        return None
    if u.scheme not in ("http", "https") or not raw_host:
        return None
    host = re.sub(r"^www\.", "", raw_host.lower())
    return next((s for h, s in bd.HOSTS.items() if host == h or host.endswith("." + h)), host)


def _leads_from(records, keyword: str, now: datetime) -> list[dict]:
    leads: list[dict] = []
    seen: set[str] = set()
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict) or rec.get("error") or rec.get("error_code") or rec.get("warning") or rec.get("warning_code"):
            continue  # a dead page or a "no results" warning is shown as empty, never filled in
        url = rec.get("url")
        if not isinstance(url, str) or url in seen:
            continue
        store = _store(url)
        if store is None:
            continue
        seen.add(url)
        title = rec.get("title")
        title = title.strip()[:MAX_TITLE] if isinstance(title, str) and title.strip() else None
        leads.append({"url": url, "store": store, "title": title, "sku": keyword, "origin": "LIVE", "kind": "lead",
                      "label": LABEL, "observed_at": bd._iso(now)})
    return leads


def _request(client: httpx.Client, headers: dict, keyword: str, limit: int) -> tuple[str, list]:
    """One discovery request; only a 202 is polled (at most MAX_POLLS). Returns (state, records). Never retries."""
    params = {"dataset_id": DATASET_ID, "format": "json", "include_errors": "true", "type": "discover_new", "discover_by": "keyword"}
    try:
        resp = client.post(f"{bd.API}/scrape", params=params, headers=headers,
                           json={"input": [{"keyword": keyword, "country": COUNTRY}], "limit_per_input": limit})
    except httpx.ReadTimeout as e:
        bd._state["error"] = type(e).__name__
        return "slow", []
    if resp.status_code == 429:
        return "blocked", []
    if resp.status_code == 400 and "not active" in resp.text.lower():
        return "not_active", []
    if resp.status_code == 202:
        try:
            snapshot_id = str(resp.json()["snapshot_id"])
        except (ValueError, KeyError, TypeError):
            return "error", []
        wait = bd._retry_after(resp)
        for _ in range(bd.MAX_POLLS):
            bd._sleep(wait)
            prog = client.get(f"{bd.API}/progress/{snapshot_id}", headers=headers)
            if prog.status_code == 429:
                return "blocked", []
            if prog.status_code != 200:
                return "error", []
            try:
                phase = str(prog.json().get("status", "")).lower()
            except (ValueError, AttributeError):
                return "error", []
            if phase == "ready":
                resp = client.get(f"{bd.API}/snapshot/{snapshot_id}", params={"format": "json"}, headers=headers)
                if resp.status_code == 429:
                    return "blocked", []
                break
            if phase in ("failed", "error"):
                return "error", []
            wait = bd._retry_after(prog)
        else:
            return "slow", []
    if resp.status_code != 200:
        return "error", []
    try:
        return "ok", resp.json()
    except ValueError:
        return "error", []


def discover(sku: str, *, client: httpx.Client | None = None, now: datetime | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Leads for `sku` (a keyword such as "rtx 5070 ti"): [{url, store, title, sku, origin:"LIVE", kind:"lead", label, observed_at}].

    Raises NotConfigured with no BRIGHT_DATA_API_KEY and makes no request; raises ValueError for a blank keyword. Every other
    outcome returns the leads found (maybe []), with the reason in brightdata.status()["last_result"]."""
    key = bd._key()
    if not key:
        bd._state["last_result"] = "not_configured"
        raise bd.NotConfigured("BRIGHT_DATA_API_KEY is not set")
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("discover needs a keyword")
    keyword = sku.strip()
    now = now or datetime.now(timezone.utc)
    if time.monotonic() < bd._state["blocked_until"]:
        bd._state["last_result"] = "blocked"
        return []
    if bd._state["calls"] >= bd.max_calls():
        bd._state["last_result"] = "budget"
        return []
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    own = client is None
    http = client or httpx.Client(verify=bd._tls(), timeout=bd.TIMEOUT)
    bd._state["calls"] += 1
    bd._state["last_call"] = bd._iso(now)
    try:
        state, records = _request(http, headers, keyword, max(1, int(limit)))
    except httpx.HTTPError as e:
        bd._state["error"] = type(e).__name__
        state, records = "error", []
    finally:
        if own:
            http.close()
    leads = _leads_from(records, keyword, now) if state == "ok" else []
    if state == "blocked":
        bd._state["blocked_until"] = time.monotonic() + bd.COOLDOWN_SECONDS
    bd._state["last_result"] = state if state != "ok" else ("ok" if leads else "empty")
    return leads
