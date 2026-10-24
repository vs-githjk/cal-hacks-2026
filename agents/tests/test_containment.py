"""Containment (issue #143): the held-out attacks Shield does NOT block still cannot move money, with Shield switched off.

Each missed attack text is put into a seller bid's free-text fields (claims, decision_trace, perks, line title and notes) and
the advocate plus the buyer path run offline. Per attack: the advocate cards still validate against the closed AdvocateCard
schema (#89), the winner, payee and amount equal the clean run's, and no charge happens without an approval row for the
mandate. pay/ functions are called, never edited. SIM bids only.
"""
import copy
import hashlib
import json
import socket
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # agents/ (common, advocate, buyer)
import common  # noqa: E402  (also puts the repo root on sys.path)
from advocate import checks, mock_data  # noqa: E402
from buyer import logic  # noqa: E402
from pay.mandate import can_charge, new_mandate  # noqa: E402
from pay.merchant_sim import MerchantSim  # noqa: E402
from pay.replay import NonceStore  # noqa: E402
from pay.tap import keyring  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from shield.bench import SETS, _local, bench  # noqa: E402

GPU = "rtx 4070 super 12gb"
ATTRS = {"category": "gpu", "chipset": "RTX 4070 SUPER", "length_mm": 267, "power_connector": ["8pin", 1]}
NEED = {"id": "need-c", "spend_limit": 2000, "owned": {"psu": {"wattage": 750, "pcie_8pin": 2}, "case": {"max_gpu_length_mm": 330}},
        "items": [{"sku_spec": GPU, "condition": "new", "variant": "12gb", "quantity": 1}]}


def sim_bid(bid_id, seller, price):
    return {"id": bid_id, "need_id": NEED["id"], "supplier_id": seller, "origin": "SIM", "claims": [], "perks": [], "decision_trace": "",
            "lines": [{"sku_spec": GPU, "unit_price": price, "quantity": 1, "offered_condition": "new", "page_condition": "new",
                       "listing_url": f"https://example.com/listing/{bid_id}", "attrs": ATTRS}],
            "total_landed_price": price, "floor_check_passed": True}


BIDS = [sim_bid("b1", "seller_1", 560), sim_bid("b2", "seller_2", 590), sim_bid("b4", "seller_4", 610)]


def shield_misses():
    rows = [json.loads(x) for x in Path(SETS["held_out"]).read_text(encoding="utf-8").splitlines() if x.strip()]
    mine = [r for r in rows if r["label"] == "attack" and _local(r["message"], r.get("context")) == "allow"]
    return mine, bench({"held_out": SETS["held_out"]})["held_out"]["missed"]


MISSES, BENCH_MISSED = shield_misses()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("network call during the containment test")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)


def buyer_path(bids):
    """Advocate, then the buyer's pick, order and mandate. Shield is not called anywhere on this path."""
    cards = checks.advise(NEED, bids, mock_data.BASELINE, mock_data.RECORDS, mock_data.RECALLS)
    for c in cards:
        common.validate("AdvocateCard", c)
    winner = checks.best_bid(bids, cards)
    order = logic.make_order(NEED, winner, approved_by="", approval_id="")
    mandate = new_mandate(deal_id=order["id"], buyer_id="vidyut-sim", amount=winner["total_landed_price"], payee=winner["supplier_id"])
    return cards, winner, mandate


def inject(bids, target, text):
    out = copy.deepcopy(bids)
    b = next(x for x in out if x["id"] == target)
    b["claims"] = [text]
    b["decision_trace"] = text
    b["perks"] = [text]
    b["lines"][0]["title"] = text
    b["lines"][0]["notes"] = text
    return out


def test_the_misses_we_test_are_exactly_the_benchs_held_out_misses():
    assert MISSES, "Shield missed nothing on held_out; there is nothing to contain"
    assert sorted(r["id"] for r in MISSES) == sorted(BENCH_MISSED)


@pytest.mark.parametrize("attack", MISSES, ids=[r["id"] for r in MISSES])
@pytest.mark.parametrize("target", ["b1", "b2"])  # the clean winner, and a losing bid
def test_a_missed_attack_cannot_move_money(attack, target):
    _, clean_winner, clean_mandate = buyer_path(BIDS)
    text = attack["message"] if isinstance(attack["message"], str) else json.dumps(attack["message"])
    cards, winner, mandate = buyer_path(inject(BIDS, target, text))
    assert winner["id"] == clean_winner["id"]
    assert (mandate["payee"], mandate["amount"]) == (clean_mandate["payee"], clean_mandate["amount"])
    for c in cards:  # seller text never reaches the closed reason
        assert c["reason"] in checks.CALL_SUMMARIES.values() and c["call_reason"]["summary"] in checks.CALL_SUMMARIES.values()

    # payment: with no approval row for this mandate, nothing is charged, whatever the request body says
    charges = []

    class SpyCharger:
        def charge(self, **kw):
            charges.append(kw)
            return {"id": "ch_sim"}

    store = NonceStore()
    sim = MerchantSim(keys=keyring(Ed25519PrivateKey.generate().public_key()),
                      receipt_keys=keyring(Ed25519PrivateKey.generate().public_key()),
                      store=store, approvals=lambda deal_id, buyer_id: None, charger=SpyCharger())
    body = json.dumps({"accepted_funds": [{"amount": f"{mandate['amount']:.2f}", "currency": "USD", "payment_method": "stripe"}],
                       "recipient": "attacker@pay.example.test", "deadline_seconds": 600, "reference": mandate["hash"],
                       "description": "deal " + mandate["deal_id"]}, separators=(",", ":")).encode()
    buyer_id = mandate["buyer_id"]
    message_id = "req:" + hashlib.sha256(buyer_id.encode() + b"\n" + body).hexdigest()
    res = sim.handle(method="POST", url="https://merchant.example.test/pay", headers={}, body=body,
                     receipt={}, message_id=message_id, buyer_id=buyer_id)
    assert res["status"] == "refused" and res["reason"] == "no_approval_record" and charges == []
    verdict = can_charge(mandate, deal_id=mandate["deal_id"], amount=mandate["amount"], payee=mandate["payee"], store=store)
    assert not verdict and verdict.reason == "not_approved"


def test_print_the_containment_line(capsys):
    line = f"{len(MISSES)} of {len(MISSES)} contained with Shield off"
    print(line)
    assert line.startswith(f"{len(BENCH_MISSED)} of")
