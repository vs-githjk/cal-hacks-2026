"""Claim check (Lane C, c3). MOCK: same I/O as the final version.

check_claim(claim) -> {"result": "verified"|"unverified"|"false", "evidence_url": str,
                       "checked_at": ISO-8601 UTC, "method": str, "evidence_hash": str}
Input is a Claim (contracts/Claim.schema.json); `result` maps to Claim.check.
The mock never fetches a page and always answers "unverified" ("could not verify").
"""
import hashlib
from datetime import datetime, timezone


def check_claim(claim):
    url = claim.get("evidence_url") or ""
    return {
        "result": "unverified",
        "evidence_url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "mock: could not verify",
        "evidence_hash": hashlib.sha256(url.encode()).hexdigest(),
    }
