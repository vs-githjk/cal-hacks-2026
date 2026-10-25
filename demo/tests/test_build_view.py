"""#345: BuildView, the pure function the build board reads. It must match contracts/samples/build-board.sample.json
(docs/changes/1650-D-build-board-shape.md), label every part and event, and never show a locked part it cannot back."""
from __future__ import annotations

import json
from pathlib import Path

from demo import build

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "samples" / "build-board.sample.json").read_text())
PART_ORDER = ["gpu", "cpu", "board", "ram", "ssd", "cooler"]
LABELS = {"psu": "750 W PSU", "case": "Case (305 mm GPU room)", "gpu": "RTX 5070 Ti", "cpu": "8-core CPU", "board": "AM5 B650 board",
          "ram": "32 GB DDR5", "ssd": "2 TB NVMe", "cooler": "Tower cooler"}
BUDGET = {"gpu": 1260.0, "cpu": 280.0, "board": 190.0, "ram": 100.0, "ssd": 120.0, "cooler": 55.0}
T = "2026-10-24T20:00:{:02d}Z"
# the sample's extension keys (docs/changes/1730-D-build-view-additions.md): the board ignores keys it does not know
EXTRA = {"part": {"origin"}, "champion": {"liveCheck"}, "event": {"origin"}, "approval": {"method", "reason"},
         "mandate": {"part"}}


def result(round_id, bid, seller, persona, rank, landed, reasons=(), origin="SIM", url=""):
    return {"roundId": round_id, "bidId": bid, "sellerId": seller, "persona": persona, "rank": rank, "landed": landed,
            "reasons": list(reasons), "origin": origin, "sourceUrl": url}


def rows(*, closed=PART_ORDER, results=None, approval=None, mandates=(), payments=(), live=None, extra_needs=()):
    needs = [{"id": f"need-{p}", "goalId": "goal-build-1", "part": p, "spendLimit": BUDGET[p], "origin": "SIM"} for p in PART_ORDER]
    rounds = [{"id": f"round-{p}", "needId": f"need-{p}", "state": "closed" if p in closed else "open", "openedAt": T.format(2),
               "closedAt": T.format(20) if p in closed else "", "origin": "SIM"} for p in PART_ORDER]
    if results is None:
        results = [result(f"round-{p}", f"b-{p}-1", f"seller_{i % 3 + 1}", f"Seller {i % 3 + 1}", 1, BUDGET[p] - 1.0)
                   for i, p in enumerate(PART_ORDER) if p in closed]
    return {"goal": {"id": "goal-build-1", "buyerId": "vidyut", "cap": 2000.0, "origin": "SIM", "type": "build"},
            "goalItems": [{"part": "psu", "label": LABELS["psu"], "skippedOwnedPartId": "owned-psu"},
                          {"part": "case", "label": LABELS["case"], "skippedOwnedPartId": "owned-case"},
                          *[{"part": p, "label": LABELS[p], "skippedOwnedPartId": ""} for p in PART_ORDER]],
            "needs": needs + list(extra_needs), "rounds": rounds + [r for n in extra_needs for r in [n.get("_round")] if r],
            "roundResults": results, "mandates": list(mandates), "approvals": [], "payments": list(payments),
            "approval": approval or {}, "liveChecks": live or {}}


def test_the_view_has_exactly_the_samples_keys_at_every_level():
    v = build.build_view(rows(), [], [])
    assert set(SAMPLE) <= set(v) and set(v) - set(SAMPLE) == set()
    assert set(SAMPLE["parts"][2]) - {"champion", "reason"} <= set(v["parts"][2]) - EXTRA["part"]
    assert set(SAMPLE["parts"][2]["champion"]) <= set(v["parts"][2]["champion"]) <= set(SAMPLE["parts"][2]["champion"]) | EXTRA["champion"]
    assert set(SAMPLE["approval"]) <= set(v["approval"]) <= set(SAMPLE["approval"]) | EXTRA["approval"]
    for e in v["events"]:
        assert set(SAMPLE["events"][0]) <= set(e) <= set(SAMPLE["events"][0]) | EXTRA["event"]
    json.dumps(v)   # plain JSON, nothing the web cannot read


def test_owned_parts_come_first_with_no_round_and_a_zero_budget():
    v = build.build_view(rows(), [], [])
    assert [p["part"] for p in v["parts"]] == ["psu", "case", *PART_ORDER]
    assert v["parts"][0] == {"part": "psu", "label": "750 W PSU", "status": "owned", "budget": 0, "origin": "SIM"}
    assert "needId" not in v["parts"][1] and "champion" not in v["parts"][1]


def test_a_closed_round_with_a_rank_one_locks_the_part_with_its_champion():
    v = build.build_view(rows(), [], [])
    gpu = v["parts"][2]
    assert gpu["status"] == "locked" and gpu["needId"] == "need-gpu" and gpu["roundId"] == "round-gpu" and gpu["budget"] == 1260.0
    assert gpu["champion"] == {"bidId": "b-gpu-1", "sellerId": "seller_1", "persona": "Seller 1", "landed": 1259.0, "origin": "SIM",
                               "sourceUrl": ""}


def test_an_open_round_is_bidding_and_a_part_with_no_round_is_planned():
    r = rows(closed=["gpu", "cpu"])
    r["rounds"] = [x for x in r["rounds"] if x["id"] not in ("round-ssd", "round-cooler")]
    v = build.build_view(r, [], [])
    by = {p["part"]: p for p in v["parts"]}
    assert by["gpu"]["status"] == "locked" and by["board"]["status"] == "bidding" and by["ssd"]["status"] == "planned"
    assert "champion" not in by["board"] and "roundId" not in by["ssd"]


def test_a_planned_part_shows_the_budget_the_plan_gave_it():
    r = rows(closed=[])
    r["needs"], r["rounds"] = [], []
    for it in r["goalItems"]:
        if it["part"] in BUDGET:
            it["budget"] = BUDGET[it["part"]]
    by = {p["part"]: p for p in build.build_view(r, [], [])["parts"]}
    assert by["gpu"]["status"] == "planned" and by["gpu"]["budget"] == 1260.0 and "needId" not in by["gpu"]


def test_spent_is_the_sum_of_the_locked_parts_landed_prices_and_never_more_than_what_is_locked():
    v = build.build_view(rows(closed=["gpu", "cpu"]), [], [])
    assert v["spent"] == round(1259.0 + 279.0, 2) and v["budget"] == 2000.0
    assert build.build_view(rows(closed=[]), [], [])["spent"] == 0


def test_a_round_whose_rank_one_is_held_back_has_no_champion_and_the_part_failed():
    held = [result("round-gpu", "b-gpu-1", "seller_1", "Seller 1", 1, 1259.0, ["held back: advocate caution (fit.gpu_length: fit not confirmed)"])]
    v = build.build_view(rows(closed=["gpu"], results=held), [], [])
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and "champion" not in gpu and "held back" in gpu["reason"]
    assert v["spent"] == 0


def test_a_round_with_every_bid_disqualified_failed_and_says_why():
    dq = [result("round-gpu", "b-gpu-1", "seller_1", "Seller 1", 0, 1299.0, ["advocate veto: fit.gpu_length 336 mm card, 305 mm case"])]
    v = build.build_view(rows(closed=["gpu"], results=dq), [], [])
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and "no eligible bid" in gpu["reason"] and "champion" not in gpu


def test_a_seller_that_never_joined_is_never_a_champion():
    cc = [result("round-gpu", "b-gpu-1", "central_computers_sf", "Central Computers (SF)", 1, 1249.99, origin="MIRROR")]
    v = build.build_view(rows(closed=["gpu"], results=cc), [], [])
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["status"] == "failed" and "not a partner" in gpu["reason"] and "champion" not in gpu


def test_a_second_need_for_a_part_makes_it_replanned_with_the_replan_events_reason():
    extra = [{"id": "need-board-2", "goalId": "goal-build-1", "part": "board", "spendLimit": 190.0, "origin": "SIM",
              "_round": {"id": "round-board-2", "needId": "need-board-2", "state": "closed", "openedAt": T.format(33), "closedAt": T.format(40),
                         "origin": "SIM"}}]
    res = [result("round-board", "b-board-1", "seller_1", "Seller 1", 1, 189.0),
           result("round-board-2", "b-board-4", "seller_2", "Seller 2", 1, 169.0)]
    events = [{"at": T.format(33), "kind": "replan", "text": "Swapped to an AM5 board, moved $20 from the SSD budget", "parts": ["board", "ssd"]}]
    v = build.build_view(rows(closed=["board"], results=res, extra_needs=extra), events, [])
    board = next(p for p in v["parts"] if p["part"] == "board")
    assert board["status"] == "replanned" and board["needId"] == "need-board-2" and board["roundId"] == "round-board-2"
    assert board["champion"]["bidId"] == "b-board-4" and "Swapped to an AM5 board" in board["reason"]


def test_checks_pass_through_with_a_safe_state():
    chk = [{"a": "cpu", "b": "board", "rule": "socket", "state": "ok", "detail": "AM5 and AM5", "source": "fit.socket"},
           {"a": "gpu", "b": "case", "rule": "case_room", "state": "maybe", "detail": "?", "source": "fit.gpu_length"}]
    v = build.build_view(rows(), [], chk)
    assert [c["state"] for c in v["checks"]] == ["ok", "unknown"] and set(v["checks"][0]) == set(SAMPLE["checks"][0])


def test_events_are_the_plan_events_then_the_markets_in_time_order_each_labelled():
    plan = [{"at": T.format(0), "kind": "plan", "text": "Plan: 6 parts to buy", "parts": []}]
    v = build.build_view(rows(), plan, [])
    kinds = [e["kind"] for e in v["events"]]
    assert kinds[0] == "plan" and kinds.count("round_open") == 6 and kinds.count("locked") == 7   # six parts and "Build ready"
    assert [e["at"] for e in v["events"]] == sorted(e["at"] for e in v["events"])
    assert all(e["origin"] in ("LIVE", "MIRROR", "SIM") for e in v["events"]) and all(isinstance(e["parts"], list) for e in v["events"])
    ready = next(e for e in v["events"] if e["kind"] == "locked" and e["parts"] == [])
    assert ready["text"].startswith("Build ready: 6 parts, 3 sellers, $")


def test_a_knockout_event_names_the_part_the_seller_and_the_markets_reason():
    res = [result("round-gpu", "b-gpu-9", "shady-sam", "Shady Sam's Deals (SIM)", 0, 1100.0, ["advocate veto: page says open box"]),
           result("round-gpu", "b-gpu-1", "seller_1", "Seller 1", 1, 1259.0)]
    v = build.build_view(rows(closed=["gpu"], results=res), [], [])
    k = next(e for e in v["events"] if e["kind"] == "knockout")
    assert k["parts"] == ["gpu"] and "Shady Sam's Deals (SIM)" in k["text"] and "page says open box" in k["text"]


def test_approval_totals_count_the_champions_and_the_distinct_sellers():
    v = build.build_view(rows(), [], [])
    assert v["approval"]["state"] == "waiting" and v["approval"]["sellers"] == 3 and v["approval"]["mandates"] == []
    assert v["approval"]["total"] == round(sum(BUDGET.values()) - 6.0, 2)


def test_mandates_list_one_entry_per_mandate_and_a_fully_paid_approval_reads_paid():
    mands = [{"hash": f"h{i}", "dealId": f"deal-b-{p}-1", "amount": BUDGET[p] - 1.0, "payee": f"seller_{i % 3 + 1}", "part": p}
             for i, p in enumerate(PART_ORDER)]
    pays = [{"mandateHash": m["hash"], "paymentRef": f"ch_sim_{m['hash']}", "amount": m["amount"], "mode": "sim", "at": T.format(55),
             "text": "SIM payment confirmed", "part": m["part"]} for m in mands]
    ap = {"state": "approved", "method": "voice_code", "events": [{"at": T.format(50), "kind": "approved", "text": "Approved on the call", "origin": "SIM"}]}
    v = build.build_view(rows(approval=ap, mandates=mands, payments=pays), [], [])
    assert v["approval"]["state"] == "paid" and len(v["approval"]["mandates"]) == 6
    assert v["approval"]["mandates"][0] == {"sellerId": "seller_1", "amount": 1259.0, "mandateHash": "h0", "part": "gpu"}
    assert [e["kind"] for e in v["events"]].count("receipt") == 6 and "approved" in [e["kind"] for e in v["events"]]
    assert build.build_view(rows(approval=ap, mandates=mands, payments=pays[:3]), [], [])["approval"]["state"] == "approved"


def test_the_builds_label_is_the_weakest_label_of_its_parts():
    assert build.build_view(rows(), [], [])["origin"] == "SIM"
    all_mirror = [result(f"round-{p}", f"b-{p}-1", "s1", "S1", 1, BUDGET[p] - 1, origin="MIRROR") for p in PART_ORDER]
    r = rows(results=all_mirror)
    for p in r["needs"]:
        p["origin"] = "MIRROR"
    assert build.build_view(r, [], [])["origin"] == "MIRROR"


def test_a_live_check_rides_on_the_champion_and_its_event_text_says_what_happened():
    live = {"gpu": {"state": "slow", "price": None, "fetchedAt": None, "origin": "MIRROR", "quoted": 1259.0, "at": T.format(45),
                    "text": "GPU: live price not read (too slow); the dated MIRROR price $1,259.00 stays"}}
    v = build.build_view(rows(live=live), [], [])
    gpu = next(p for p in v["parts"] if p["part"] == "gpu")
    assert gpu["champion"]["liveCheck"]["state"] == "slow" and gpu["champion"]["liveCheck"]["origin"] == "MIRROR"
    assert any("live price not read" in e["text"] and e["parts"] == ["gpu"] for e in v["events"])


def test_the_function_is_pure_it_changes_nothing_it_is_given():
    r = rows()
    before = json.dumps(r, sort_keys=True)
    build.build_view(r, [{"at": T.format(0), "kind": "plan", "text": "x", "parts": []}], [])
    assert json.dumps(r, sort_keys=True) == before


def test_the_samples_own_top_level_types_hold():
    v = build.build_view(rows(), [], [])
    for k, want in (("goalId", str), ("buyerId", str), ("budget", float), ("spent", float), ("origin", str)):
        assert isinstance(v[k], want)


def test_events_with_the_same_second_keep_the_story_order_plan_rounds_ready_live_check_call_receipts():
    rr = rows(approval={"state": "approved", "events": [{"at": T.format(5), "kind": "call", "text": "Calling", "origin": "SIM"},
                                                        {"at": T.format(5), "kind": "approved", "text": "Approved", "origin": "SIM"}]},
              mandates=[{"hash": "h", "dealId": "d", "amount": 1.0, "payee": "s", "part": "gpu"}],
              payments=[{"mandateHash": "h", "paymentRef": "ch_1", "amount": 1.0, "mode": "sim", "at": T.format(5), "text": "SIM payment", "part": "gpu"}],
              live={"gpu": {"state": "ok", "price": 1.0, "fetchedAt": None, "origin": "LIVE", "quoted": 1.0, "at": T.format(5), "text": "GPU: live"}})
    for r in rr["rounds"]:
        r["openedAt"], r["closedAt"] = T.format(5), T.format(5)
    v = build.build_view(rr, [{"at": T.format(5), "kind": "plan", "text": "Plan", "parts": []}], [])
    order = [e["kind"] for e in v["events"]]
    assert order[0] == "plan" and order[1] == "round_open"
    assert order.index("locked") < order.index("call") < order.index("approved") < order.index("receipt")
    texts = [e["text"] for e in v["events"]]
    assert texts.index(next(t for t in texts if t.startswith("Build ready"))) < texts.index("GPU: live") < texts.index("Calling")
