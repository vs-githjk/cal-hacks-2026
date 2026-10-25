"""#342 item 3: seller_6, the uAgent that bids Central Computers (SF) listings as MIRROR. Additive only: no existing
address, seed, name or port changes. No default seed. Its bid is shown for comparison and never reaches an order or a
payment, on the seller side as well as the buyer side (#333)."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENTS))
sys.path.insert(0, str(AGENTS / "sellers"))

import common  # noqa: E402
import factory  # noqa: E402
import run_all  # noqa: E402
from agents.sellers import seller_agent  # noqa: E402
from agents.sellers.test_seller_agent import (BUYER_AGENT, BUYER_ID, SELLER_ADDR, Context, FakeAgent,  # noqa: E402
                                              FakeProtocol, approved_transaction, charge_transaction,
                                              load_transaction, save_transaction)
from data.mirror import not_partners  # noqa: E402
from policy import make_bid  # noqa: E402
from shield.core import screen as shield_screen  # noqa: E402
from uagents_core.contrib.protocols.payment import CommitPayment  # noqa: E402

LABEL = "MIRROR: real Central Computers listing captured Oct 24 21:12 UTC via Apify. Central Computers is not a partner."
PRIVATE = "a-private-test-seed-for-seller-6-only"
NEED = {"id": "need-342", "buyer_id": "b1", "consent": True, "auction_window_s": 60, "source": "live",
        "owned": {"case": {"max_gpu_length_mm": 305}},
        "items": [{"sku_spec": "rtx 5070 ti", "condition": "new", "variant": "retail", "quantity": 1}]}


def _common_in_a_fresh_process(seed):
    """What common sees for SELLER_6_AGENT_SEED=seed (an empty value also masks any agents/.env entry)."""
    env = {**os.environ, "SELLER_6_AGENT_SEED": seed}
    code = ("import json, common\n"
            "try:\n    a = common.address('seller_6')\nexcept ValueError as e:\n    a = 'ERR ' + str(e)\n"
            "print(json.dumps({'sellers': common.SELLERS, 'seeded': 'seller_6' in common.SEEDS, 'address': a,"
            " 'others': [common.address(s) for s in common.CATALOG_SELLERS]}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=AGENTS, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_entries_are_additive_and_the_port_is_reserved():
    assert common.CATALOG_SELLERS == [f"seller_{i}" for i in range(1, 6)] == common.SELLERS[:5]
    assert {n: common.SELLER_PORTS[n] for n in common.CATALOG_SELLERS} == {
        "seller_1": 8011, "seller_2": 8012, "seller_3": 8013, "seller_4": 8014, "seller_5": 8015}
    assert common.SELLER_PORTS["seller_6"] == 8016 and len(set(common.SELLER_PORTS.values())) == len(common.SELLER_PORTS)
    assert 8016 in factory.RESERVED_PORTS and "seller_6" in factory.PORT_OWNERS[8016]
    assert factory.pick_port({}, start=8016) != 8016
    assert "seller_6" in common.BUILT_IN_ROLES and "seller_6" in common.MIRROR_SELLERS
    readme = Path(seller_agent.__file__).with_name("AGENTVERSE-seller_6.md").read_text()
    assert LABEL in readme and "cannot be bought here" in readme and "not the store" in readme
    assert all(s in readme for s in ("## Summary", "## Features", "## Usage examples", "## Use cases", "## Limitations"))
    assert chr(0x2014) not in readme and chr(0x2013) not in readme


@pytest.mark.parametrize("seed", ["", "   ", "short-seed", "tech-bazaar-seller_6-dev", "x" * 20 + "-dev"])
def test_no_private_seed_means_seller_6_stays_off_and_never_gets_a_guessable_key(seed):
    got = _common_in_a_fresh_process(seed)
    assert "seller_6" not in got["sellers"] and not got["seeded"]
    assert got["address"].startswith("ERR seller_6 is off: set SELLER_6_AGENT_SEED")


def test_a_private_seed_turns_seller_6_on_without_moving_any_other_agent():
    off, on = _common_in_a_fresh_process(""), _common_in_a_fresh_process(PRIVATE)
    from uagents.crypto import Identity
    assert on["sellers"] == [*off["sellers"], "seller_6"] and on["seeded"]
    assert on["address"] == Identity.from_seed(PRIVATE, 0).address
    assert on["others"] == off["others"]  # seller_1 to seller_5 keep their addresses


def test_build_without_the_seed_fails_clearly(monkeypatch):
    monkeypatch.delitem(common.SEEDS, "seller_6", raising=False)
    with pytest.raises(SystemExit, match="SELLER_6_AGENT_SEED"):
        seller_agent.build("seller_6")


@pytest.fixture
def seller_6(tmp_path, monkeypatch):
    db_path = tmp_path / ".state" / "state.sqlite3"
    monkeypatch.setattr(seller_agent.state, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setitem(common.SEEDS, "seller_6", PRIVATE)
    monkeypatch.setattr(seller_agent, "Agent", FakeAgent)
    monkeypatch.setattr(seller_agent, "Protocol", FakeProtocol)
    args = {}
    monkeypatch.setattr(seller_agent.common, "agent_args", lambda role, port, **kw: args.update(role=role, port=port,
                                                                                              **kw) or {})
    chats = []
    monkeypatch.setattr(seller_agent.common, "include_profile_chat", lambda _agent, text: chats.append(text))
    monkeypatch.setattr(seller_agent.common, "address", lambda role: BUYER_AGENT if role == "buyer" else role)
    monkeypatch.setattr(seller_agent.common, "screen", lambda *_a, **_k: {"verdict": "allow", "reasons": []})
    app = seller_agent.build("seller_6")
    pay = next(p for p in app.protocols if CommitPayment in p.handlers)
    return {"app": app, "pay": pay.handlers, "args": args, "chat": chats[0], "db_path": db_path}


def _bid_reply(seller_6, need=NEED):
    ctx = Context()
    asyncio.run(seller_6["app"].handlers[common.BidRequest](ctx, BUYER_AGENT, common.BidRequest(need_json=json.dumps(need))))
    [(to, reply)] = ctx.sent
    assert to == BUYER_AGENT
    return json.loads(reply.bid_json), reply.persona_line


def test_seller_6_builds_from_mirror_seller_on_its_port_with_an_honest_profile(seller_6):
    args = seller_6["args"]
    assert args["role"] == "seller_6" and args["port"] == 8016 and args["name"] == "Central Comp MIRROR" and len(args["name"]) < 20
    assert args["readme_path"].endswith("AGENTVERSE-seller_6.md") and args["handle"] == "techbazaarseller6"
    assert LABEL in args["description"] and not_partners.NOT_ORDERABLE in args["description"]
    assert "not the store" in seller_6["chat"] and LABEL in seller_6["chat"]
    for text in (args["description"], seller_6["chat"]):
        assert chr(0x2014) not in text and chr(0x2013) not in text


def test_seller_6_bids_mirror_under_its_own_id_with_the_label(seller_6):
    bid, persona = _bid_reply(seller_6)
    common.validate("Bid", bid)
    assert bid["supplier_id"] == bid["seller_id"] == "seller_6" and bid["origin"] == "MIRROR"
    assert bid["orderable"] is False and not not_partners.orderable(bid) and bid["mirror_label"] == LABEL
    assert bid["persona"] == "Central Computers (SF)" and bid["lines"][0]["listing_url"].startswith(
        "https://www.centralcomputer.com/")
    assert bid["lines"][0]["attrs"]["length_mm"] <= 305 and bid["lines"][0]["offered_condition"] == "unknown"
    assert persona.startswith(LABEL) and "shown for comparison" in persona
    ctx = {"sender_role": "seller", "payee_of_record": None, "price_history": []}
    assert shield_screen(json.dumps(bid), ctx, classifier=None)["verdict"] == "allow"
    assert shield_screen(persona, ctx, classifier=None)["verdict"] == "allow"


def test_seller_6_bids_nothing_over_its_stock(seller_6):
    need = dict(NEED, items=[dict(NEED["items"][0], quantity=4)])
    ctx = Context()
    asyncio.run(seller_6["app"].handlers[common.BidRequest](ctx, BUYER_AGENT, common.BidRequest(need_json=json.dumps(need))))
    assert not ctx.sent


def test_seller_6_never_sends_a_payment_request_even_for_a_fully_approved_order(seller_6):
    """The same approved transaction that makes seller_1 send its payment request (test_seller_agent) gets nothing."""
    transaction = approved_transaction()
    save_transaction(seller_6["db_path"], transaction)
    ctx = Context()
    order = common.OrderPlaced(order_json=json.dumps(transaction["order"]), mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller_6["app"].handlers[common.OrderPlaced](ctx, BUYER_AGENT, order))
    assert not ctx.sent and any("never ordered" in line for line in ctx.logs)


def test_seller_6_never_completes_a_payment_even_for_a_matching_charge(seller_6):
    transaction = approved_transaction()
    save_transaction(seller_6["db_path"], transaction)
    commit = charge_transaction(seller_6["db_path"], transaction)
    ctx = Context()
    asyncio.run(seller_6["pay"][CommitPayment](ctx, BUYER_AGENT, commit))
    assert not ctx.sent and any("never paid" in line for line in ctx.logs)
    assert load_transaction(seller_6["db_path"], transaction["deal_id"], BUYER_ID)["mandate"]["payee"] == SELLER_ADDR


def test_the_bureau_runs_seller_6_only_with_its_seed(monkeypatch, capsys):
    built = []
    monkeypatch.setattr(run_all, "build", lambda name: built.append(name) or type("A", (), {"address": name})())
    monkeypatch.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))
    run_all.build_all()
    assert built == common.CATALOG_SELLERS and "seller_6 off: set SELLER_6_AGENT_SEED" in capsys.readouterr().out
    built.clear()
    monkeypatch.setattr(common, "SELLERS", [*common.CATALOG_SELLERS, "seller_6"])
    monkeypatch.setitem(common.SEEDS, "seller_6", PRIVATE)
    assert [a.address for a in run_all.build_all()] == [*common.CATALOG_SELLERS, "seller_6"]


def test_a_seller_6_bid_is_held_back_by_every_buyer_check():
    from advocate import checks
    from buyer import hunt
    bid = make_bid(NEED, seller_agent._mirror_for("seller_6", NEED))
    card = checks.advise(NEED, [bid], {}, {}, [], NEED["owned"])[0]
    assert card["recommendation"] == "veto" and card["rule_id"] == "advocate.mirror_not_orderable"
    assert hunt.pick_best([bid], {bid["id"]: {"recommendation": "buy"}}, {"seller_6"}) is None
