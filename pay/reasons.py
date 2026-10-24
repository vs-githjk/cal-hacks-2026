"""Call-reason templates (a10): turn an advocate verdict into the closed schema the call script reads.

reason_for({"rule_id", "source_url"}) returns exactly {rule_id, summary, source_url}. The summary is looked up
by rule_id in SUMMARIES and is never taken from the caller, from seller text or from a model. A rule id that
is not in the table gets the generic template (and the id "advocate.unknown", so an unknown id is never echoed
or spoken). A source_url that is not a plain http(s) link is replaced by FALLBACK_SOURCE.

SUMMARIES mirrors agents/advocate/checks.py CALL_SUMMARIES (Lane A) plus the other fit-checker rule ids. Every
entry must pass pay.callscript.clean_advocate_reason (tested): letters, digits and . , % ' - only, none of the
words the call script blocks, no dashes.
"""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from pay.callscript import _host

GENERIC_RULE_ID = "advocate.unknown"
GENERIC_SUMMARY = "The advocate flagged this offer, and the details are on your screen"
FALLBACK_SOURCE = "https://github.com/vs-githjk/cal-hacks-2026/blob/main/agents/advocate/checks.py"
MAX_URL = 500

SUMMARIES: dict[str, str] = {
    "advocate.condition": "The listing page shows a different condition than the seller claims",
    "advocate.recall": "This product matches a CPSC recall entry",
    "advocate.price": "The price is more than 10 percent above its price history",
    "advocate.spec": "This offer is not the condition you asked for",
    "advocate.record": "This seller has a caution record",
    "advocate.floor": "This bid did not pass the price floor check",
    "advocate.same_seller": "Another bid in this round comes from the same seller",
    "advocate.unsourced": "A claim on this bid could not be checked against its listing",
    "advocate.fit_unknown": "Fit could not be confirmed from the listing details",
    "advocate.ok": "No problems found in the checks",
    "advocate.mirror_not_orderable": "This store is shown for comparison only and cannot be bought from here",
    "fit": "This part does not fit your build",
    "fit.gpu_length": "The card is longer than your case allows",
    "fit.psu_wattage": "Your power supply is below what this card needs",
    "fit.gpu_connectors": "Your power supply lacks the connectors this card needs",
    "fit.cpu_socket": "The processor socket does not match the board",
    "fit.ram_type": "The memory type does not match the board",
    "fit.ram_slots": "The board does not have enough memory slots for this kit",
    "fit.form_factor": "The board does not fit your case",
    "fit.psu_form_factor": "The power supply does not fit your case",
    "fit.cooler_height": "The cooler is taller than your case allows",
    "fit.cooler_socket": "The cooler does not support this processor socket",
    "fit.storage": "The drive type does not match what your board supports",
    "fit.no_checks": "Fit could not be confirmed from the listing details",
    "fit.ok": "No fit problems found in the checks",
    "claim.stock": "The stock claim could not be confirmed on the listing page",
    "claim.delivery": "The delivery claim could not be confirmed on the listing page",
    "claim.fees": "The listing page shows fees that the bid did not mention",
    "claim.returns": "The return policy on the listing page differs from the claim",
    "claim.price": "The price on the listing page differs from the claim",
    "claim.spec": "A spec on the listing page differs from the claim",
}


def _good_url(url: Any) -> bool:
    if not isinstance(url, str) or not url or len(url) > MAX_URL or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme in ("http", "https") and parts.username is None and parts.password is None
                and _host(url) is not None)
    except ValueError:
        return False


def reason_for(verdict: Any) -> dict[str, str]:
    """The closed-schema reason for one advocate verdict. Never raises; unknown input gets the generic answer."""
    v = verdict if isinstance(verdict, Mapping) else {}
    rid = v.get("rule_id")
    known = isinstance(rid, str) and rid in SUMMARIES
    url = v.get("source_url")
    return {
        "rule_id": rid if known else GENERIC_RULE_ID,
        "summary": SUMMARIES[rid] if known else GENERIC_SUMMARY,
        "source_url": url if _good_url(url) else FALLBACK_SOURCE,
    }
