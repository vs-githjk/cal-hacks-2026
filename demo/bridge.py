#!/usr/bin/env python3
"""Screen bridge: play the demo beats (real lane code, demo/run_demo.py) into the running SpacetimeDB market,
step by step, so /buyer and /market on the web app show Vidyut's round live.

    python3 demo/bridge.py                       # one run, 2 s between steps, against the local market
    python3 demo/bridge.py --step-delay 3 --reset  # slower, and wipe the demo tables first (reset_demo)
    python3 demo/bridge.py --dry-run             # print the reducer calls, touch nothing

Every write goes through the existing reducer with its required role token. Sellers publish through MarketBridge with
complete line metadata; the referee opens review, attaches checks bound to the selected lines, then closes the round.
The mandate is created only after exact winner readback. Approval and payment are not bridged because there is no verified
checkout evidence path. No role gate is bypassed. The only owner action is `assign_role` for demo seller identities.

What the market has no reducer or column for is NOT faked: the console prints it as NOT BRIDGED at the end and
demo/README.md lists the gaps for Lane B. Pure mapping (run -> steps) is `plan`; the live part is `execute`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.common import MIRROR, SIM, Narrator, money  # noqa: E402

DB_BUYER_ID = "vidyut"          # the id /buyer pairs with (web DEMO_BUYER) and the only one with a pairing code
BUYER_TOKEN, REFEREE_TOKEN = "buyer-vidyut.json", "referee.json"
MANDATE_MINUTES = 10
MIN_WINDOW_S = 6
REVIEW_WINDOW_S = 20
LIVE_TAGS = {"MIRROR", "SIM", "LIVE"}


@dataclass
class Step:
    actor: str                       # "buyer", "referee" or "seller:<seller_id>"
    reducer: str
    args: dict = field(default_factory=dict)
    say: str = ""
    tag: str = SIM
    pause: bool = False              # wait --step-delay after this call (the step shows on screen)
    pace: float = 1.0                # multiplier on the delay (round 2 runs faster)
    close: bool = False              # wait for the round deadline, then close it
    window_s: int = 0                # open_round only: the window this step asked for
    review: bool = False             # first close_round opens review; the next one finalizes


# ---------------------------------------------------------------- the mapping (pure, tested with a fake client)

def _line(bid: dict, index: int, sku: str) -> dict:
    l = bid["lines"][index]
    return {"sku_spec": sku, "offered_spec": "", "offered_condition": l["offered_condition"],
            "unit_price": l["unit_price"], "quantity": l["quantity"]}


def _line_metadata(bid: dict, *, seller_shipping: Optional[float] = None) -> list[dict]:
    """Hash the exact captured listing record (MIRROR) or exact SIM bid line; never guess a digest."""
    rows = []
    for index, line in enumerate(bid["lines"]):
        listing_id = line.get("listing_id") or line.get("listing_url")
        source = line.get("listing_url")
        if not listing_id or not source:
            raise RuntimeError("line listing metadata is incomplete")
        digest = line.get("listing_hash")
        if digest is None and line.get("origin") == MIRROR:
            matches = [p for p in (ROOT / "data" / "mirror" / "snapshots").glob("*.json")
                       if line.get("snapshot_id") and p.stem == line["snapshot_id"]]
            cards = json.loads(matches[0].read_text(encoding="utf-8")) if len(matches) == 1 else []
            card = next((card for card in cards if card.get("id") == listing_id), None)
            if card is not None:
                digest = hashlib.sha256(json.dumps(card, sort_keys=True, separators=(",", ":"),
                                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if digest is None and line.get("origin") == SIM:
            digest = hashlib.sha256(json.dumps(line, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RuntimeError("line listing hash is unavailable")
        shipping = line["shipping"] if "shipping" in line else seller_shipping
        if isinstance(shipping, bool) or not isinstance(shipping, (int, float)) or not math.isfinite(shipping) or shipping < 0:
            raise RuntimeError("line shipping metadata is unavailable")
        rows.append({"lineIndex": index, "shipping": shipping, "listingId": listing_id, "listingHash": digest,
                     "source": source, "snapshotId": line.get("snapshot_id", ""),
                     "provenance": {"origin": line.get("origin", bid.get("origin", SIM))},
                     "attrs": line.get("attrs") or {}})
    if not rows:
        raise RuntimeError("bid has no line metadata")
    return rows


def _entries(ranking: dict) -> dict:
    """seller_id -> the ranking entry (ranked or disqualified) carrying the picked line index."""
    return {e["seller_id"]: e for e in [*ranking["ranked"], *ranking["disqualified"]]}


def _seller_shipping(seller_id: str) -> float:
    """Read shipping from the same offline seller fixtures used to build the demo bids."""
    from demo.sellers import all_sellers

    matches = [seller for seller in all_sellers()[0] if seller.id == seller_id]
    if len(matches) != 1:
        raise RuntimeError("seller shipping fixture is unavailable")
    return matches[0].shipping


def _seller_fixture(seller_id: str) -> Any:
    from demo.sellers import all_sellers

    matches = [seller for seller in all_sellers()[0] if seller.id == seller_id]
    return matches[0] if len(matches) == 1 else None


def _claim_line_index(bid: dict, claim: dict) -> Optional[int]:
    """Map a claim to its original line using the seller fixture when URLs are shared."""
    seller = _seller_fixture(bid["seller_id"])
    if seller is not None:
        matches = [i for i, fixture_claim in enumerate(seller.claims)
                   if fixture_claim.get("text") == claim.get("text")
                   and fixture_claim.get("evidence_url") == claim.get("evidence_url")]
        if len(matches) == 1 and len(seller.claims) == len(seller.lines):
            index = matches[0]
            fixture_line = seller.lines[index]
            bid_line = bid["lines"][index]
            if (seller.claims[index]["evidence_url"] == fixture_line.listing_url
                    and bid_line.get("listing_url") == fixture_line.listing_url
                    and bid_line.get("offered_condition") == fixture_line.condition):
                return index
    matches = [i for i, line in enumerate(bid["lines"]) if line.get("listing_url") == claim.get("evidence_url")]
    return matches[0] if len(matches) == 1 else None


def bid_id(bid: dict, round_no: int) -> str:
    return bid["id"] if round_no == 1 else f"{bid['id']}-r{round_no}"


def round_steps(*, round_no: int, need_id: str, bids: list[dict], ranking: dict, sellers: dict, shield: list[dict],
                claims: dict, cards: list[dict], delay: float, pace: float) -> list[Step]:
    """open_round, every seller's floor and sealed bid in arrival order, then the Shield, claim-check and advocate results.
    A bid carries ALL its condition lines (alternatives for one SKU); the market picks the cheapest allowed one."""
    round_id = f"round-{round_no}"
    sku = bids[0]["lines"][0]["sku_spec"]
    entry = _entries(ranking)
    claim_bindings: dict[str, list[dict]] = {}
    for bid in bids:
        selected_index = entry.get(bid["seller_id"], {}).get("line", 0)
        seller_shipping = sellers[bid["seller_id"]].get("shipping")
        for claim in claims.get(bid["id"], []):
            line_index = _claim_line_index(bid, claim)
            if line_index is None or line_index != selected_index:
                continue
            metadata = _line_metadata(bid, seller_shipping=seller_shipping)[line_index]
            claim_bindings.setdefault(bid["id"], []).append({
                "claim": claim, "line_index": line_index, "listing_id": metadata["listingId"],
                "listing_hash": metadata["listingHash"]})
    seller_steps: list[Step] = []
    for bid in bids:
        sid = bid["seller_id"]
        idx = entry.get(sid, {}).get("line", 0)
        seller = sellers[sid]
        placed = bid["lines"][idx]                       # the line the demo picked: its price and listing are the bid's headline
        floor = min(l["floor"] for l in seller["lines"])   # the market keeps one floor per SKU; the lowest never blocks a line
        alts = f" (alternatives, the market picks the cheapest allowed: " + " | ".join(
            f"{l['offered_condition']} {l['unit_price']:,.2f}" for l in bid["lines"]) + ")" if len(bid["lines"]) > 1 else ""
        seller_steps.append(Step(f"seller:{sid}", "set_floor", {"sku_spec": sku, "floor": floor}, tag=bid["origin"],
                                 say=f"{bid['persona']} sets a private floor"))
        seller_steps.append(Step(
            f"seller:{sid}", "place_bid",
            {"id": bid_id(bid, round_no), "round_id": round_id, "persona": bid["persona"],
             "lines": [_line(bid, i, sku) for i in range(len(bid["lines"]))],
             "stated_total": placed["unit_price"] * placed["quantity"], "perks": list(bid["perks"]),
             "claims": [row["claim"]["text"] for row in claim_bindings.get(bid["id"], [])],
             "origin": bid["origin"], "source": placed["listing_url"], "seller_id": sid,
             "line_metadata": _line_metadata(bid, seller_shipping=seller.get("shipping"))},
            tag=bid["origin"], pause=True, pace=pace,
            say=f"{bid['persona']} seals a bid: {placed['offered_condition']} {money(placed['unit_price'])}{alts}"))
    rejected = {e["bid_id"] for e in ranking["disqualified"] if e.get("kind") == "rejected"}   # floor: never screened
    check_steps: list[Step] = []
    for v in shield:
        if v["bid_id"] in rejected:
            continue
        bid = next(b for b in bids if b["id"] == v["bid_id"])
        check_steps.append(Step("referee", "attach_verdict",
                                {"bid_id": bid_id(bid, round_no), "verdict": v["verdict"], "rule_ids": list(v["rule_ids"]), "origin": SIM},
                                tag=SIM,
                                say=f"Bazaar Shield (real shield.screen) on {bid['persona']}: {v['verdict']}"))
    for bid in bids:
        for row in claim_bindings.get(bid["id"], []):
            c = row["claim"]
            check_steps.append(Step("referee", "attach_claim_check",
                                    {"bid_id": bid_id(bid, round_no), "claim": c["text"], "check": c["check"],
                                     "evidence_url": c["evidence_url"], "origin": c["origin"],
                                     "line_index": row["line_index"], "listing_id": row["listing_id"],
                                     "listing_hash": row["listing_hash"]},
                                    tag=c["origin"],
                                    say=f"claim check (real data.claim_check) on {bid['persona']}: {c['check']}: {c['text']}"))
    bid_of = {b["id"]: b for b in bids}
    for c in cards:        # the advocate's real card for every bid it judged; a veto disqualifies it at the close
        bid = bid_of[c["bid_id"]]
        why = c["call_reason"]
        check_steps.append(Step("referee", "attach_advocate_card",
                                {"bid_id": bid_id(bid, round_no), "recommendation": c["recommendation"], "rule_id": why["rule_id"],
                                 "text": why["summary"], "source_url": why["source_url"], "origin": bid["origin"]},
                                tag=bid["origin"],
                                say=f"advocate (Lane A checks.advise) on {bid['persona']}: {c['recommendation'].upper()} "
                                    f"{why['rule_id']}: {why['summary']}"))
    paused = sum(s.pace for s in [*seller_steps, *check_steps] if s.pause)
    window = max(MIN_WINDOW_S, math.ceil(paused * delay) + 6)
    opener = Step("referee", "open_round", {"round_id": round_id, "need_id": need_id, "window_s": window}, window_s=window,
                  tag=SIM, pause=True, pace=pace, say=f"round {round_no} opens sealed for {window} s")
    review = Step("referee", "close_round", {"round_id": round_id}, close=True, review=True, tag=SIM, pause=True, pace=pace,
                  say=f"round {round_no} reaches its bid cutoff and opens the review window")
    closer = Step("referee", "close_round", {"round_id": round_id}, close=True, tag=SIM, pause=True, pace=pace,
                  say=f"round {round_no} closes after review: the market ranks and reveals every bid")
    return [opener, *seller_steps, review, *check_steps, closer]


def plan(run: dict, *, delay: float = 2.0, buyer_id: str = DB_BUYER_ID, rounds: int = 1) -> list[Step]:
    """Map a demo run (demo.run_demo.run_all) to reducer calls, in the order the stage story tells it."""
    b = run["beats"]
    goal, need, b2 = b["1"]["goal"], b["1"]["need"], b["2"]
    sellers = {}
    for seller in b2["sellers"]:
        bid = next((bid for bid in b2["bids"] if bid["seller_id"] == seller["id"]), None)
        shipping = seller.get("shipping")
        if shipping is None and bid is not None and any("shipping" not in line for line in bid["lines"]):
            shipping = _seller_shipping(seller["id"])
        sellers[seller["id"]] = {**seller, "shipping": shipping}
    steps: list[Step] = []

    # beat 1: Vidyut's goal and need (the buyer token posts both, for its own buyer id)
    conds = goal["items"][0].get("allowed_conditions") or [goal["items"][0]["condition"]]
    items = [{"sku_spec": i["sku_spec"], "condition": " or ".join(conds) if i["part"] == "gpu" else i["condition"],
              "variant": i["variant"], "quantity": i["quantity"], "skipped_owned_part_id": i.get("skipped_owned_part_id", "")}
             for i in goal["items"]]
    steps.append(Step("buyer", "post_goal",
                      {"id": goal["id"], "buyer_id": buyer_id, "type": goal["type"], "cap": goal["cap"], "deadline": goal["deadline"],
                       "po_number": "", "origin": SIM, "items": items},
                      pause=True, say=f"Vidyut (DB buyer id {buyer_id}) sets a goal: {b['1']['goal_text']}"))
    n = need["items"][0]
    steps.append(Step("buyer", "post_need",
                      {"id": need["id"], "buyer_id": buyer_id, "goal_id": goal["id"], "delivery_window": need["delivery_window"],
                       "spend_limit": need["spend_limit"], "consent": need["consent"], "auction_window_s": need["auction_window_s"],
                       "origin": SIM,
                       "items": [{"sku_spec": n["sku_spec"], "condition": n["condition"],
                                  "allowed_conditions": list(n.get("allowed_conditions") or []), "variant": n["variant"],
                                  "quantity": n["quantity"], "unit": n["unit"]}]},
                      pause=True, say=f"the need goes to sellers: {n['sku_spec']}, {' or '.join(n.get('allowed_conditions') or [n['condition']])}; the cap is withheld from them"))

    # beat 2: the sealed round (Shield and claim checks attach before the close; the market ranks)
    steps += round_steps(round_no=1, need_id=need["id"], bids=b2["bids"], ranking=b2["ranking"], sellers=sellers, shield=b2["shield"],
                         claims=b2["claims"], cards=b2["cards"], delay=delay, pace=1.0)

    # beat 4: mandate only after the final server result matches the local demo result.
    m, win = b["4"]["mandate"], b2["winner"]
    wbid = next(x for x in b2["bids"] if x["id"] == win["bid_id"])
    steps.append(Step("referee", "create_mandate",
                      {"hash": m["hash"], "id": m["id"], "deal_id": m["deal_id"], "buyer_id": buyer_id,
                       "goal_id": goal["id"], "need_id": need["id"], "_round_id": "round-1", "amount": m["amount"],
                       "payee": m["payee"], "expiry_minutes": MANDATE_MINUTES, "nonce": m["nonce"], "requested_by": "",
                       "origin": m["origin"]},
                      tag=m["origin"], pause=True,
                      say=f"mandate for {wbid['persona']}: {money(m['amount'])} to {m['payee']} (a SIM test address)"))

    # beat 5: round 2 with the learning seller's lowered price (record_loss_report exists but is not wired here)
    if rounds >= 2:
        r2 = b["5"]["round2"]
        steps += round_steps(round_no=2, need_id=need["id"], bids=r2["bids"], ranking=r2["ranking"], sellers=sellers,
                             shield=b2["shield"], claims=b2["claims"], cards=r2["cards"], delay=delay, pace=0.5)
    return steps


# What the market cannot take today (printed at the end of every run; mirrored in demo/README.md for Lane B).
NOT_BRIDGED = [
    "loss reports: market reducer record_loss_report exists, but this legacy bridge does not call it; beat 5's report and learning step remain console only.",
    "claim checks with missing or ambiguous evidence URLs are skipped because they cannot be bound to one original listing line.",
    "goal state: create_mandate sets the goal to HOLD_FOR_CALL when the deal exceeds allowance; this bridge does not mirror the earlier HUNTING transition or later DONE transition.",
    "buyer allowance: no set_allowance reducer, so /buyer shows the market's fresh $0 allowance, not Vidyut's $250 per purchase "
    "(the deal still correctly needs the call).",
    "voice approval and payment: no verified checkout evidence path exists, so local SIM call/code/charge output is not written as public approval or payment proof.",
    "beat 3 injected-listing block: the market has no reducer for this separate message, so it is not attached to an already closed seller bid.",
    "buyer name and seller personas: /buyer is hardcoded to the id vidyut and prints 'Buyer: Vidyut'; persona rows come only "
    "from seed_demo (Seller A to C), so the 3D floor has no personas for the demo sellers.",
    "seller floors per condition: the market keeps one floor per SKU, so a seller with several condition lines gets its lowest floor "
    "(issue #18 asks for a floor per seller, SKU and condition).",
]


# ---------------------------------------------------------------- the live part

def execute(steps: list[Step], clients: dict, *, delay: float, say: Callable[[Step], None],
            bridges: Optional[dict] = None, run: Optional[dict] = None,
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
    """Run the steps in order. A reducer refusal stops the run with the market's own message."""
    deadline: Optional[float] = None
    candidates: dict[str, dict] = {}
    bridges = bridges or {}
    for s in steps:
        say(s)
        client = clients[s.actor]
        if s.close:
            for attempt in range(32):
                if deadline is not None and clock() < deadline:
                    sleep(deadline - clock())
                try:
                    client.call(s.reducer, **s.args)
                    break
                except RuntimeError as e:
                    msg = str(e)
                    if "already closed" in msg:
                        break
                    if ("still open" in msg or "review period is still open" in msg) and attempt < 31:
                        sleep(1.0)    # an anti-snipe extension moved the deadline
                        continue
                    raise
            if s.review:
                referee = bridges.get("referee")
                if referee is None:
                    raise RuntimeError("MarketBridge referee is required for review readback")
                rows = referee.review_candidates(s.args["round_id"])
                for candidate in rows:
                    if run is None or candidate.get("need_id") != run["beats"]["1"]["need"]["id"]:
                        raise RuntimeError("review candidate need does not match")
                    binding = candidate.get("binding_hash")
                    bid = candidate.get("bid_id")
                    lines = candidate.get("lines")
                    metadata = candidate.get("line_metadata")
                    need_items = run["beats"]["1"]["need"]["items"]
                    expected = {item["sku_spec"]: item["quantity"] for item in need_items}
                    if (not isinstance(binding, str) or len(binding) != 64 or any(c not in "0123456789abcdef" for c in binding)
                            or not isinstance(bid, str) or bid in candidates or not isinstance(lines, list)
                            or len(lines) != len(expected) or not isinstance(metadata, list)):
                        raise RuntimeError("review candidate readback is incomplete")
                    metadata_by_index = {}
                    for row in metadata:
                        if not isinstance(row, dict):
                            raise RuntimeError("review candidate line binding is incomplete")
                        index = row.get("lineIndex")
                        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in metadata_by_index:
                            raise RuntimeError("review candidate line binding is incomplete")
                        metadata_by_index[index] = row
                    seen: set[str] = set()
                    for line in lines:
                        index = line.get("line_index") if isinstance(line, dict) else None
                        row = metadata_by_index.get(index)
                        if (isinstance(index, bool) or not isinstance(index, int) or index < 0
                                or not isinstance(row, dict) or row.get("listingId") != line.get("listing_id")
                                or row.get("listingHash") != line.get("listing_hash")
                                or line.get("sku_spec") not in expected or line.get("sku_spec") in seen
                                or line.get("quantity", 0) < expected[line.get("sku_spec")]):
                            raise RuntimeError("review candidate line binding is incomplete")
                        seen.add(line["sku_spec"])
                    if seen != set(expected):
                        raise RuntimeError("review candidate does not cover the need")
                    candidates[bid] = candidate
                deadline = clock() + REVIEW_WINDOW_S
        else:
            if s.reducer == "place_bid":
                bridge = bridges.get(s.actor)
                if bridge is None:
                    raise RuntimeError("MarketBridge seller is required to publish bids")
                args = dict(s.args)
                args["bid_id"] = args.pop("id")
                bridge.publish_bid(**args)
            elif s.reducer == "attach_advocate_card":
                candidate = candidates.get(s.args["bid_id"])
                if candidate is None:
                    raise RuntimeError("AdvocateCard has no bound review candidate")
                bridges["referee"].attach_advocate_card(**{**s.args, "binding_hash": candidate["binding_hash"]})
            elif s.reducer == "attach_claim_check":
                candidate = candidates.get(s.args["bid_id"])
                if candidate is None:
                    raise RuntimeError("claim check has no bound review candidate")
                line_index = s.args.get("line_index")
                line = next((line for line in candidate["lines"] if line.get("line_index") == line_index), None)
                if (line is None or line.get("listing_id") != s.args.get("listing_id")
                        or line.get("listing_hash") != s.args.get("listing_hash")):
                    raise RuntimeError("claim evidence does not match its bound review line")
                bridges["referee"].attach_claim_check(
                    **{**s.args, "binding_hash": candidate["binding_hash"]})
            elif s.reducer == "create_mandate":
                if run is None or "buyer" not in bridges:
                    raise RuntimeError("MarketBridge buyer and local run are required before a mandate")
                local_bid_id = run["beats"]["2"]["winner"]["bid_id"]
                _verify_market_winner(bridges["buyer"], run, s.args["need_id"], s.args["_round_id"],
                                      candidates.get(local_bid_id))
                client.call(s.reducer, **{key: value for key, value in s.args.items() if not key.startswith("_")})
            elif s.reducer in {"record_approval", "record_payment"}:
                raise RuntimeError("checkout evidence is unavailable; approval and payment are not bridged")
            else:
                client.call(s.reducer, **s.args)
        if s.window_s:
            deadline = clock() + s.window_s
        if s.pause and delay > 0:
            sleep(delay * s.pace)


def _verify_market_winner(market_bridge: Any, run: dict, need_id: str, round_id: str,
                          candidate: Optional[dict]) -> dict:
    b1, b2 = run["beats"]["1"], run["beats"]["2"]
    need_items = b1["need"]["items"]
    winner = b2.get("winner")
    bid = b2.get("winner_bid")
    if winner is None or bid is None or candidate is None or need_id != b1["need"]["id"]:
        raise RuntimeError("local winner or need is incomplete")
    observed = market_bridge.authoritative_winner(round_id, need_items)
    if observed is None:
        raise RuntimeError("market winner readback is missing or incomplete")
    line_index = winner.get("line")
    if isinstance(line_index, bool) or not isinstance(line_index, int) or not 0 <= line_index < len(bid["lines"]):
        raise RuntimeError("local winner line is incomplete")
    line = bid["lines"][line_index]
    seller_shipping = _seller_shipping(bid["seller_id"]) if any("shipping" not in line for line in bid["lines"]) else None
    meta = _line_metadata(bid, seller_shipping=seller_shipping)[line_index]
    try:
        amount = Decimal(str(run["beats"]["4"]["mandate"]["amount"])) * 100
        local = Decimal(str(winner["landed"])) * 100
        if not amount.is_finite() or not local.is_finite() or amount != amount.to_integral_value() or local != local.to_integral_value():
            raise ValueError
        amount_cents, local_cents = int(amount), int(local)
    except (InvalidOperation, ValueError, TypeError, OverflowError, KeyError):
        raise RuntimeError("local winner amount is invalid") from None
    expected_quantity = need_items[0]["quantity"] if len(need_items) == 1 else None
    lines = observed.get("lines")
    if (len(need_items) != 1 or not isinstance(lines, list) or len(lines) != 1
            or observed.get("round_id") != round_id or observed.get("bid_id") != winner.get("bid_id")
            or observed.get("seller_id") != winner.get("seller_id") or winner.get("bid_id") != bid.get("id")
            or candidate.get("need_id") != need_id or observed.get("binding_hash") != candidate.get("binding_hash")
            or observed.get("origin") != bid.get("origin") or observed.get("source") != line.get("listing_url")
            or observed.get("landed_cents") != amount_cents or amount_cents != local_cents):
        raise RuntimeError("market winner does not exactly match the local winner")
    selected = lines[0]
    if (not isinstance(selected, dict) or selected.get("sku_spec") != need_items[0].get("sku_spec")
            or selected.get("unit_price") != line.get("unit_price")
            or selected.get("quantity") != expected_quantity
            or selected.get("original_line_index") != line_index
            or selected.get("listing_id") != meta["listingId"]
            or selected.get("listing_hash") != meta["listingHash"]
            or selected.get("shipping") != meta["shipping"]):
        raise RuntimeError("market winner line metadata does not exactly match the local listing")
    return observed


def compare_to_db(rows: list, run: dict) -> list[str]:
    """Lines saying whether the market's round-1 ranking matches the demo's. Rows are round_result rows in table order:
    id, round_id, bid_id, seller_id, persona, rank, landed, reasons, ... (round-1 only)."""
    b2 = run["beats"]["2"]
    demo_win = next(s for s in b2["sellers"] if s["id"] == b2["winner"]["seller_id"])["name"]
    r1 = sorted((r for r in rows if r[1] == "round-1"), key=lambda r: (r[5] or 99, r[4]))
    ranked = [r for r in r1 if r[5]]
    out = [f"market ranking (round 1): " + ", ".join(f"#{r[5]} {r[4]} {money(r[6])}" for r in ranked)]
    for r in (r for r in r1 if not r[5]):
        reasons = r[7] if len(r) > 7 and isinstance(r[7], list) else []
        out.append(f"market OUT: {r[4]} {money(r[6])}: " + ("; ".join(reasons) or "no reason given"))
    if ranked and ranked[0][3] != b2["winner"]["seller_id"]:
        out.append(f"DIVERGENCE: the demo's winner is {demo_win}; the market ranks {ranked[0][4]} first. "
                   f"The mandate that follows is the demo's winner, not the market's #1.")
    elif not ranked:
        out.append("DIVERGENCE: the market ranked no bid.")
    else:
        out.append(f"market and demo agree on the winner: {demo_win}")
    return out


def assign_seller_roles(seller_ids: list[str], clients: dict, spacetime: str, server: str, db: str) -> None:
    """Owner step, the same call market/scripts/setup_roles.py makes: one seller identity per demo seller."""
    for sid in seller_ids:
        ident = clients[f"seller:{sid}"].identity
        subprocess.run([spacetime, "call", "-s", server, db, "assign_role", f'"0x{ident}"', '"seller"', f'"{sid}"'],
                       check=True, capture_output=True)


def find_tokens_dir(explicit: Optional[str]) -> Path:
    cands = [Path(explicit)] if explicit else [Path(os.environ["BRIDGE_TOKENS_DIR"])] if os.environ.get("BRIDGE_TOKENS_DIR") else []
    cands += [ROOT / ".tokens", ROOT.parent / "lane-d-launcher" / ".tokens", ROOT.parent / "lane-d" / ".tokens"]
    for c in cands:
        if (c / REFEREE_TOKEN).exists() and (c / BUYER_TOKEN).exists():
            return c
    raise SystemExit("no tokens dir with referee.json and buyer-vidyut.json (run market/scripts/setup_roles.py, or pass --tokens-dir)")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Play the demo beats into the running SpacetimeDB market so /buyer and /market show them")
    ap.add_argument("--step-delay", type=float, default=2.0, help="seconds between visible steps (default 2)")
    ap.add_argument("--rounds", type=int, choices=[1, 2], default=1,
                    help="2 also plays beat 5's round 2 (default 1)")
    ap.add_argument("--reset", action="store_true", help="call reset_demo first (referee): wipes needs, goals, rounds; keeps roles and pair codes")
    ap.add_argument("--dry-run", action="store_true", help="print the reducer calls only")
    ap.add_argument("--stripe", action="store_true", help="disabled pending verified checkout evidence; winner readback gate is enabled")
    ap.add_argument("--tokens-dir", help="folder with referee.json and buyer-vidyut.json (default: auto-detect)")
    ap.add_argument("--buyer-id", default=DB_BUYER_ID, help="DB buyer id (default vidyut, the id /buyer pairs with)")
    ap.add_argument("--no-assign-roles", action="store_true", help="skip the owner assign_role step for seller identities")
    ap.add_argument("--server", default=os.environ.get("SPACETIMEDB_SERVER", "local"))
    args = ap.parse_args(argv)

    if args.stripe:
        Narrator(True).note("STOPPED: winner readback is enforced; --stripe remains disabled pending verified checkout evidence.")
        return 2

    from demo.run_demo import run_all
    run = run_all(say=Narrator(False))
    steps = plan(run, delay=args.step_delay, buyer_id=args.buyer_id, rounds=args.rounds)
    out = Narrator(True)
    out.note("Tech Bazaar screen bridge: demo beats (real lane code) -> existing SpacetimeDB reducers")
    out.note(f"{len(steps)} reducer calls, {args.step_delay} s between visible steps. Open /buyer (pair as {args.buyer_id}) and /market.")
    out.note("Buyer: Vidyut. Goal and owned parts are SIM. Tags: [MIRROR] real dated listing, [SIM] generated by us.")

    def say(s: Step) -> None:
        who = "buyer" if s.actor == "buyer" else "referee" if s.actor == "referee" else s.actor.replace("seller:", "seller ")
        if s.reducer == "set_floor":
            return
        out.line(s.tag if s.tag in LIVE_TAGS else SIM, f"{who:<26}{s.reducer:<22}{s.say}")

    if args.dry_run:
        for s in steps:
            say(s)
        out.blank()
        for g in NOT_BRIDGED:
            out.note("NOT BRIDGED: " + g)
        return 0

    try:
        return _run_live(args, steps, run, out, say)
    except (OSError, subprocess.CalledProcessError) as e:
        out.blank()
        if isinstance(e, subprocess.CalledProcessError):
            err = (e.stderr or b"").decode(errors="replace").strip().splitlines()
            out.note(f"STOPPED: spacetime CLI failed: {err[0] if err else e}")
        else:
            out.note(f"STOPPED: market not reachable at {os.environ.get('SPACETIMEDB_HTTP', 'http://127.0.0.1:3000')} "
                     f"({type(e).__name__}). Start it with `python3 scripts/launch.py up` or check SPACETIMEDB_HTTP.")
        return 1


def _run_live(args, steps, run, out, say) -> int:
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market   # the market's own bridge; reads SPACETIMEDB_HTTP and SPACETIMEDB_DB
    tokens = find_tokens_dir(args.tokens_dir)
    out.note(f"tokens: {tokens}")
    seller_tokens = ROOT / ".tokens"
    seller_tokens.mkdir(exist_ok=True)
    clients: dict[str, Any] = {"buyer": Market(token_file=str(tokens / BUYER_TOKEN)),
                               "referee": Market(token_file=str(tokens / REFEREE_TOKEN))}
    from agents.market_bridge import MarketBridge
    bridges: dict[str, Any] = {role: MarketBridge(role, client=client) for role, client in clients.items()}
    seller_ids = sorted({s.actor.split(":", 1)[1] for s in steps if s.actor.startswith("seller:")})
    for sid in seller_ids:
        clients[f"seller:{sid}"] = Market(token_file=str(seller_tokens / f"bridge-{sid}.json"))
        bridges[f"seller:{sid}"] = MarketBridge("seller", client=clients[f"seller:{sid}"])
    if not args.no_assign_roles:
        spacetime = shutil.which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")
        from stdb import DB
        assign_seller_roles(seller_ids, clients, spacetime, args.server, DB)
    if args.reset:
        out.note("reset_demo (referee): clearing the demo tables")
        clients["referee"].call("reset_demo")
        time.sleep(1)
    try:
        execute(steps, clients, bridges=bridges, run=run, delay=args.step_delay, say=say)
    except RuntimeError as e:
        out.blank()
        out.note(f"STOPPED by the market: {e}")
        if "already exists" in str(e):
            out.note("hint: this need or round is already in the database; run again with --reset")
        return 1
    out.blank()
    try:
        rows = clients["referee"].sql("SELECT * FROM round_result")
        for line in compare_to_db(rows, run):
            out.note(line)
    except Exception as e:  # reading back is a courtesy; the run itself succeeded
        out.note(f"could not read round_result back ({type(e).__name__})")
    out.blank()
    for g in NOT_BRIDGED:
        out.note("NOT BRIDGED: " + g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
