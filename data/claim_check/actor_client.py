"""Call the public claim-check Actor for one claim, failing safe (Lane C, issue #205).

check_via_actor(claim, post=None, timeout=6.0) -> the same dict as check_claim: {result, evidence_url, checked_at, method,
evidence_hash, reason}. Every way the Actor can fail gives result "unverified", never "verified", with reason
"claim check unavailable" and the case in `method`:
  down (no connection or a 5xx) | slow (no answer within `timeout`, or Apify's own run timeout 408) |
  quota (402 or 429) | empty (the run returned no row for this claim) | error (any other status or an unreadable body).
One request per claim and no retry: a retry after a slow run could start a second run and charge twice (#172 keeps one
charge per run; this keeps one run per claim). An unverified claim is not a veto, so money still moves only through
the normal approval (agents/tests/test_containment.py). Reads APIFY_TOKEN from the environment; never logs it.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

ACTOR = "anoopibrampur~tech-bazaar-claim-check"
URL = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
TIMEOUT = 6.0  # docs/ARCHITECTURE.md: external calls time out after 4 to 6 seconds
UNAVAILABLE = "claim check unavailable"
PAID_BY_AGENT = "using a prepaid agent token (set in the env)"  # #290: an env var, not proof of a paid run
RESULTS = ("verified", "unverified", "false")


class Slow(Exception):
    """The request got no answer within the bound."""


class Down(Exception):
    """No connection to Apify."""


def _http_post(url, body, headers, timeout):
    import httpx
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException as e:
        raise Slow(type(e).__name__) from None
    except httpx.TransportError as e:
        raise Down(type(e).__name__) from None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def _unavailable(claim, case, detail=""):
    url = claim.get("evidence_url")
    return {"result": "unverified", "evidence_url": url if isinstance(url, str) else "",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": f"{UNAVAILABLE}: {case}" + (f" ({detail})" if detail else ""), "evidence_hash": "", "reason": UNAVAILABLE}


def check_via_actor(claim: dict, post=None, timeout: float = TIMEOUT) -> dict:
    claim = claim if isinstance(claim, dict) else {}
    post = post or _http_post
    agent = os.environ.get("APIFY_AGENT_TOKEN", "")  # #270: a prepaid token the agent bought itself (x402 or MPP at agi.apify.com)
    token = agent or os.environ.get("APIFY_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return {**_check(claim, post, timeout, headers), "paid_by": PAID_BY_AGENT if agent else "our Apify account"}


def _check(claim: dict, post, timeout: float, headers: dict) -> dict:
    try:
        status, rows = post(f"{URL}?timeout={max(1, math.ceil(timeout))}", {"claims": [claim]}, headers, timeout)
    except Slow:
        return _unavailable(claim, "slow", f"no answer within {timeout:g} s")
    except Down as e:
        return _unavailable(claim, "down", str(e))
    except Exception:  # anything else fails safe too; no detail, so a token in an exception message cannot leak
        return _unavailable(claim, "error")
    if not isinstance(status, int) or isinstance(status, bool):
        return _unavailable(claim, "error", "no status")
    if status == 408:
        return _unavailable(claim, "slow", "Apify run timeout")
    if status in (402, 429):
        return _unavailable(claim, "quota", f"HTTP {status}")
    if status >= 500:
        return _unavailable(claim, "down", f"HTTP {status}")
    if status not in (200, 201):
        return _unavailable(claim, "error", f"HTTP {status}")
    if not isinstance(rows, list):
        return _unavailable(claim, "error", "unreadable body")
    try:  # reading rows never raises: anything unexpected is unverified
        return _read(claim, rows)
    except Exception:
        return _unavailable(claim, "error")


def _http_url(url) -> bool:
    if not isinstance(url, str):
        return False
    try:
        u = urlparse(url)
    except ValueError:
        return False
    try:
        host = u.hostname  # "http://user@/x" and "http://:80/x" have a netloc but no host
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(host)


def _read(claim: dict, rows: list) -> dict:
    """Only rows naming this claim's id count. Rows that disagree, or a verdict without its own http(s) page and page hash,
    are unverified."""
    cid = claim.get("id")
    mine = [r for r in rows if isinstance(r, dict) and cid is not None and type(r.get("id")) is type(cid) and r.get("id") == cid]
    if not mine:  # the id must match in value and type, so True never matches a claim id of 1
        return _unavailable(claim, "empty", "no row for this claim")
    if len({(repr(r.get("result")), repr(r.get("evidence_url")), repr(r.get("evidence_hash"))) for r in mine}) > 1:
        return _unavailable(claim, "error", "rows for this claim disagree")  # same verdict, page and hash, or none of them
    row = mine[0]
    if row.get("result") not in RESULTS:
        return _unavailable(claim, "error", "row has no valid result")
    if row["result"] == "unverified":
        return {**_unavailable(claim, "empty"), "method": str(row.get("method") or "apify actor"), "reason": str(row.get("reason") or "could not verify")}
    url, h = row.get("evidence_url"), row.get("evidence_hash")
    if not _http_url(url):  # the row's own page, so the hash is tied to the page that was read (same rule as check_claim)
        return _unavailable(claim, "error", "evidence url is not an http or https page")
    if not (isinstance(h, str) and h.strip()):  # verified or false always comes with the page hash
        return _unavailable(claim, "error", "verdict without a page hash")
    return {"result": row["result"], "evidence_url": url,
            "checked_at": str(row.get("checked_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
            "method": str(row.get("method") or "apify actor"), "evidence_hash": h.strip(), "reason": str(row.get("reason") or "")}
