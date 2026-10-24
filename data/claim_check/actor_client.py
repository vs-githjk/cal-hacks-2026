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
    return {"result": "unverified", "evidence_url": claim.get("evidence_url") or "",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": f"{UNAVAILABLE}: {case}" + (f" ({detail})" if detail else ""), "evidence_hash": "", "reason": UNAVAILABLE}


def check_via_actor(claim: dict, post=None, timeout: float = TIMEOUT) -> dict:
    post = post or _http_post
    token = os.environ.get("APIFY_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
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
    cid = claim.get("id")
    row = next((r for r in rows if isinstance(r, dict) and cid is not None and r.get("id") == cid), None)
    if row is None and len(rows) == 1 and isinstance(rows[0], dict) and rows[0].get("id") in (None, cid):  # a lone row naming another claim is not ours
        row = rows[0]
    if not isinstance(row, dict):
        return _unavailable(claim, "empty", "no row for this claim")
    if row.get("result") not in RESULTS:
        return _unavailable(claim, "error", "row has no valid result")
    url = row.get("evidence_url") or claim.get("evidence_url") or ""
    if not isinstance(url, str) or urlparse(url).scheme not in ("http", "https"):  # same rule as check_claim
        return _unavailable(claim, "error", "evidence url is not http or https")
    if row["result"] != "unverified" and not row.get("evidence_hash"):  # verified or false always comes with the page hash
        return _unavailable(claim, "error", "verdict without a page hash")
    return {"result": row["result"], "evidence_url": url,
            "checked_at": row.get("checked_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": row.get("method") or "apify actor", "evidence_hash": row.get("evidence_hash") or "", "reason": row.get("reason") or ""}
