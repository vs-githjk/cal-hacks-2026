"""Offline scan of real (MIRROR) listings for claims their own structured data does not support (issue #140).

    python3 -m data.claim_check.real_scan     # writes data/claim_check/real_catches.json

For every saved listing (data/mirror/snapshots*/*.json) the claims come from its own title text (parse_claims) and the page
facts from its own structured fields (condition, was price, stock). was-price is judged only against our dated MIRROR
captures of that URL (the #136 rule). No network. Wording is neutral; a hit says the title differs from the listing's own
data at the capture time, nothing about the seller. Listings are never edited or planted.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import _history, judge, parse_claims

MIRROR = Path(__file__).resolve().parents[1] / "mirror"
OUT = Path(__file__).resolve().parent / "real_catches.json"
RULES = ("condition", "was_price", "stock")


def snapshot_files() -> list[Path]:
    return sorted(p for d in sorted(MIRROR.glob("snapshots*")) for p in d.glob("*.json"))


def _stock_text(v):
    return v.replace("_", " ") if isinstance(v, str) else v


def facts_of(card: dict) -> dict:
    listing = card.get("listing") or {}
    facts = {"price": card.get("price"), "was_price": listing.get("was_price"), "stock": _stock_text(listing.get("stock"))}
    if card.get("condition") not in (None, "unknown"):
        facts["condition"] = card["condition"]
    return facts


def check_card(card: dict, observations: list[dict]) -> list[dict]:
    """Every rule result for one saved listing: [{rule_id, result, claim_text, page_evidence, reason}]."""
    at = card.get("snapshot_date") or ""
    facts = facts_of(card)
    url = (card.get("listing") or {}).get("url") or card.get("source")
    out = []
    for field, value in parse_claims({"text": card.get("name") or ""}):
        if field not in RULES:
            continue
        series = _history(url, facts, None, None, observations) if field == "was_price" else None
        result, reason = judge(field, value, facts, at, series)
        out.append({"rule_id": field, "result": result, "claim_text": card.get("name"), "reason": reason,
                    "page_evidence": {k: facts.get(k) for k in ("condition", "was_price", "stock") if facts.get(k) is not None}})
    return out


def scan(files: list[Path] | None = None, observations: list[dict] | None = None) -> dict:
    if observations is None:
        from data.baselines import observations as load
        observations = load()
    files = snapshot_files() if files is None else files
    listings, catches, judged = 0, [], {}
    for f in files:
        for card in json.loads(f.read_text()):
            listings += 1
            for r in check_card(card, observations):
                judged[r["result"]] = judged.get(r["result"], 0) + 1
                if r["result"] == "false":
                    catches.append({"url": (card.get("listing") or {}).get("url") or card.get("source"), "snapshot_id": card.get("snapshot_id"),
                                    "snapshot_date": card.get("snapshot_date"), "claim_text": r["claim_text"],
                                    "page_evidence": r["page_evidence"], "rule_id": r["rule_id"], "result": r["result"], "reason": r["reason"]})
    return {"origin": "MIRROR", "scanned": {"listings": listings, "files": [f.name for f in files], "rules": list(RULES), "claims_judged": judged}, "catches": catches}


if __name__ == "__main__":
    res = scan()
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(f"scanned {res['scanned']['listings']} listings in {len(res['scanned']['files'])} files; {len(res['catches'])} catches")
    for c in res["catches"]:
        print(f"  {c['rule_id']}: {c['claim_text'][:60]} -> {c['reason']}")
