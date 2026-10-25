"""The four minds wired into the running seller agents: bid handler, order handler, chat, roster."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from uagents import Model
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # agents/, for common

import common  # noqa: E402
from agents.buyer import state
from agents.sellers import learner, mind_store, mirror_live, minds, refurb, seller_agent, seller_chat, trickster
from agents.sellers.test_seller_agent import (  # noqa: F401  (seller is a pytest fixture used by the order test)
    BUYER_AGENT, FakeAgent, FakeProtocol, Context, approved_transaction, save_transaction, seller)
from data.mirror import not_partners

TI = "rtx 5070 ti"
PRIVATE = "a-private-test-seed-for-seller-six-1234567890"
REPORTS: dict = {"rows": []}


class Bridge:
    published: list = []

    def __init__(self, *a, **k):
        pass

    def my_loss_reports(self):
        return list(REPORTS["rows"])

    def publish_bid(self, **kw):
        Bridge.published.append(kw)


def need(nid="need-1", source="sim", qty=1):
    return {"id": nid, "source": source, "owned": {}, "items": [
        {"sku_spec": TI, "condition": "new", "allowed_conditions": ["new", "open-box", "refurbished"], "variant": "retail",
         "quantity": qty}]}


def loss(rid, round_id, market_id, reason="price", band="within5"):
    return {"id": rid, "round_id": round_id, "seller_id": market_id, "won": False, "gap_band": band, "reason": reason,
            "source_url": "https://shop.example/x", "created_at": "2026-10-25T01:00:00Z"}


@pytest.fixture
def built(tmp_path, monkeypatch):
    REPORTS["rows"] = []
    Bridge.published = []
    db_path = tmp_path / ".state" / "state.sqlite3"
    monkeypatch.setattr(state, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(seller_agent, "Agent", FakeAgent)
    monkeypatch.setattr(seller_agent, "Protocol", FakeProtocol)
    monkeypatch.setattr(seller_agent, "MarketBridge", Bridge)
    monkeypatch.setenv("SPACETIMEDB_SELLER_A_TOKEN_FILE", "unused")
    monkeypatch.setenv("SPACETIMEDB_SELLER_C_TOKEN_FILE", "unused")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
    monkeypatch.setitem(common.SEEDS, "seller_6", PRIVATE)
    chats = []
    monkeypatch.setattr(seller_agent.common, "agent_args", lambda role, port, **kw: {})
    monkeypatch.setattr(seller_agent.common, "include_profile_chat", lambda agent, text, **kw: chats.append((text, kw)))
    monkeypatch.setattr(seller_agent.common, "address", lambda role: BUYER_AGENT if role == "buyer" else role)
    monkeypatch.setattr(seller_agent.common, "screen", lambda *a, **k: {"verdict": "allow", "reasons": []})
    monkeypatch.setattr(seller_agent.common, "shield_context", lambda *a, **k: {})
    mirror_live.LAST.clear()

    def make(name):
        app = seller_agent.build(name)
        return app, chats[-1]

    def ask(app, n):
        ctx = Context()
        asyncio.run(app.handlers[common.BidRequest](ctx, BUYER_AGENT, common.BidRequest(need_json=json.dumps(n))))
        return ctx, [(json.loads(m.bid_json), m.persona_line) for _, m in ctx.sent]

    return {"make": make, "ask": ask, "db_path": db_path, "chats": chats}


def mind(built, name):
    db = mind_store.open_store(built["db_path"])
    try:
        return minds.load(db, name)
    finally:
        db.close()


# ---- Byte Bros: the learner ------------------------------------------------

def test_byte_bros_learns_from_its_own_loss_reports_across_rounds_and_shows_the_note(built):
    app, _ = built["make"]("seller_1")
    ctx, [(first, _)] = built["ask"](app, need("need-1"))
    assert first["strategy_note"] == "Bid 1 round(s), no result yet: holding 3% off list."
    REPORTS["rows"] = [loss("l1", "round-need-1", "seller-a", band="within10")]
    ctx, [(second, _)] = built["ask"](app, need("need-2"))
    assert second["lines"][0]["unit_price"] < first["lines"][0]["unit_price"]
    assert second["strategy_note"].startswith("Lost 1 of 1, last by under 10%, stepping toward 9.8% off list")
    assert second["strategy_note"] in second["decision_trace"]
    assert mind(built, "seller_1")["cut"] == 0.07
    REPORTS["rows"].append(loss("l2", "round-need-2", "seller-a", band="within5"))
    ctx, [(third, _)] = built["ask"](app, need("need-3"))
    floor = 1239.0   # Byte Bros' 5070 Ti floor: a 7 percent cut would go under it, so the bid sits on the floor, never below
    assert second["lines"][0]["unit_price"] == floor and third["lines"][0]["unit_price"] == floor
    assert third["floor_check_passed"] and "at my price limit" in third["strategy_note"]
    assert mind(built, "seller_1")["cut"] > 0.07                          # it still learned the bigger step
    common.validate("Bid", third)


def test_a_trusted_order_tells_the_learner_it_won_and_probes_margin_back(built, seller):
    db_path = seller["db_path"]
    db = mind_store.open_store(db_path)
    st = learner.fresh()
    st["cut"] = 0.07
    minds.save(db, "seller_1", st)
    db.close()
    transaction = approved_transaction()
    save_transaction(db_path, transaction)
    ctx = Context()
    order = common.OrderPlaced(order_json=json.dumps(transaction["order"]), mandate_json=json.dumps(transaction["mandate"]))
    asyncio.run(seller["order_handler"](ctx, BUYER_AGENT, order))
    assert len(ctx.sent) == 1                                  # the payment request still goes out
    db = mind_store.open_store(db_path)
    won = minds.load(db, "seller_1")
    db.close()
    assert won["wins"] == 1 and won["cut"] == pytest.approx(0.065) and won["best_win_cut"] == 0.07


# ---- Frankie: the trickster -----------------------------------------------

def test_by_default_frankie_plays_only_what_the_live_path_catches_and_learns_from_a_veto(built, monkeypatch):
    monkeypatch.delenv("SELLER3_EXTRA_TRICKS", raising=False)
    app, _ = built["make"]("seller_3")
    ctx, [(one, _)] = built["ask"](app, need("need-1"))
    assert one["lines"][0]["page_condition"] == "open-box"                   # round 1: the condition lie (Advocate veto)
    REPORTS["rows"] = [loss("a", "round-need-1", "seller-c", reason="advocate_veto")]
    ctx, [(two, persona2)] = built["ask"](app, need("need-2"))
    assert trickster.INJECTION in two["claims"] and two["lines"][0]["page_condition"] == "new"   # round 2: the injection (Smell Test)
    assert _smell(two, persona2)["verdict"] == "block"
    seen = []
    for n in range(3, 9):
        ctx, [(bid, _)] = built["ask"](app, need(f"need-{n}"))
        seen.append("condition_lie" if bid["lines"][0]["page_condition"] == "open-box" else
                    "prompt_injection" if trickster.INJECTION in bid["claims"] else "EXTRA")
    assert "EXTRA" not in seen and set(seen) == {"condition_lie", "prompt_injection"}
    st = mind(built, "seller_3")
    assert st["tried"]["hidden_fee"] == st["tried"]["fake_warranty"] == 0


def test_frankie_rotates_through_all_four_tricks_only_with_the_extra_flag(built, monkeypatch):
    monkeypatch.setenv("SELLER3_EXTRA_TRICKS", "1")
    app, _ = built["make"]("seller_3")
    ctx, [(one, persona1)] = built["ask"](app, need("need-1"))
    assert one["lines"][0]["offered_condition"] == "new" and one["lines"][0]["page_condition"] == "open-box"   # round 1: the condition lie
    assert persona1.startswith("FlashDeal Frankie: $")
    REPORTS["rows"] = [loss("a", "round-need-1", "seller-c", reason="advocate_veto")]
    ctx, [(two, persona2)] = built["ask"](app, need("need-2"))
    assert two["lines"][0]["page_condition"] == "new"                       # the condition is honest this round
    assert "no fees" in " ".join(two["claims"]) and "no fees" in persona2    # round 2: the hidden fee
    st = mind(built, "seller_3")
    assert st["caught"]["condition_lie"] == 1 and st["current"]["trick"] == "hidden_fee"
    ctx, [(two_again, _)] = built["ask"](app, need("need-2"))               # the same round asked twice keeps its trick
    assert two_again["claims"] == two["claims"]
    ctx, [(three, _)] = built["ask"](app, need("need-3"))                   # silence about round 2: presumed caught, next trick
    assert "3-year warranty included" in three["claims"]
    assert mind(built, "seller_3")["caught"]["hidden_fee"] == 1


def test_frankies_floor_line_and_total_are_unchanged_by_its_trick(built):
    app, _ = built["make"]("seller_3")
    [(bid, _)] = built["ask"](app, need("need-1"))[1]
    assert bid["total_landed_price"] == round(1249.0 * 0.98 + 9.99, 2) and bid["floor_check_passed"]
    assert "trick" not in json.dumps(bid).lower()


# ---- ReNew: the honest refurbisher ---------------------------------------

def test_renew_bids_labelled_lines_and_says_the_tradeoff_on_the_floor(built):
    app, _ = built["make"]("seller_5")
    ctx, [(bid, persona)] = built["ask"](app, need())
    assert {l["offered_condition"] for l in bid["lines"]} == {"refurbished", "open-box"}
    assert bid["tradeoff"] and persona == refurb.persona(bid)
    assert "90-day warranty instead of 1-year" in persona
    common.validate("Bid", bid)


# ---- Central Comp MIRROR ----------------------------------------------------

def test_the_mirror_bids_the_dated_snapshot_with_its_capture_time_when_no_key_is_set(built):
    app, _ = built["make"]("seller_6")
    ctx, [(bid, persona)] = built["ask"](app, need(source="live"))
    assert bid["origin"] == "MIRROR" and bid["orderable"] is False and not not_partners.orderable(bid)
    assert bid["price_anchor"]["source"] == "snapshot" and bid["price_anchor"]["as_of"] == "2026-10-24 21:12 UTC"
    assert "Snapshot captured 2026-10-24 21:12 UTC" in persona and persona.startswith("MIRROR: real Central Computers listing")
    assert "Snapshot captured 2026-10-24 21:12 UTC" in bid["decision_trace"]


def test_the_mirror_rechecks_every_round_and_a_live_price_reaches_the_bid_and_the_persona(built, monkeypatch):
    calls = []

    def recheck(listing, now=None):
        calls.append(listing["url"])
        return {"state": "price_changed", "price": 1199.99 - 10 * len(calls), "origin": "LIVE",
                "fetched_at": "2026-10-25T02:30:04+00:00", "quoted": listing["price"]}

    monkeypatch.setattr(mirror_live.recheck_mod, "recheck", recheck)
    app, _ = built["make"]("seller_6")
    ctx, [(one, p1)] = built["ask"](app, need("need-1", "live"))
    ctx, [(two, p2)] = built["ask"](app, need("need-2", "live"))
    assert len(calls) == 2 and calls[0].startswith("https://www.centralcomputer.com/")
    assert one["lines"][0]["unit_price"] == 1189.99 and two["lines"][0]["unit_price"] == 1179.99
    assert "Re-checked live through Bright Data" in p1 and one["price_anchor"]["source"] == "live"
    assert two["orderable"] is False and two["origin"] == "MIRROR"


def test_the_mirror_skips_the_recheck_for_a_part_it_does_not_bid_and_bids_nothing_when_out_of_stock(built, monkeypatch):
    calls = []
    monkeypatch.setattr(mirror_live.recheck_mod, "recheck", lambda l, now=None: calls.append(1) or {
        "state": "out_of_stock", "price": 1249.99, "origin": "LIVE", "fetched_at": "2026-10-25T02:30:04+00:00"})
    app, _ = built["make"]("seller_6")
    other = need("need-x", "live")
    other["items"][0]["sku_spec"] = "rtx 4070 super 12gb"
    ctx, sent = built["ask"](app, other)
    assert sent == [] and calls == []
    ctx, sent = built["ask"](app, need("need-y", "live"))
    assert sent == [] and calls == [1] and any("Out of stock at the store" in line for line in ctx.logs)


# ---- chat wiring --------------------------------------------------------------

@pytest.mark.parametrize("name", ["seller_1", "seller_3", "seller_5", "seller_6"])
def test_the_four_named_sellers_get_an_in_character_answer_in_their_profile_chat(built, name):
    app, (text, kw) = built["make"](name)
    assert callable(kw["answer"]) and "this chat cannot place orders" in text or name == "seller_6"
    reply = asyncio.run(kw["answer"]("who are you?"))      # PR #459's contract: an async answer(text)
    assert {"seller_1": "Byte Bros", "seller_3": "Frankie", "seller_5": "ReNew", "seller_6": "MIRROR"}[name] in reply
    assert reply.endswith(seller_chat.SIM_TAG) == (name != "seller_6")


def test_a_custom_seller_keeps_the_fixed_chat_text(built):
    cfg = {"id": "acme-parts", "name": "Acme Parts", "archetype": "test shop", "origin": "SIM", "pricing": {"mode": "discount", "discount": 0.05},
           "shipping": 0.0, "perks": [], "claims": [],
           "listings": {TI: {"price": 1300.0, "floor_by_condition": {"new": 1200.0}, "condition": "new", "page_condition": "new",
                             "variant": "retail", "listing_url": "https://acme.example/5070ti",
                             "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti"}}}}
    common.SEEDS.pop("acme-parts", None)
    try:
        seller_agent.build("acme-parts", cfg)
    finally:
        common.SEEDS.pop("acme-parts", None)
        common._CUSTOM_ENVS.pop("ACME_PARTS", None)
    assert built["chats"][-1][1] == {}


# ---- the shared profile chat ---------------------------------------------------

def _chat_handler(answer):
    fake = Mock()
    common.include_profile_chat(fake, "ROLE TEXT buyer", answer=answer)
    protocol = fake.include.call_args.args[0]
    return protocol.signed_message_handlers[Model.build_schema_digest(ChatMessage)]


def _run(handler, monkeypatch, verdict="allow"):
    sent = []
    monkeypatch.setattr(common, "screen", lambda *a, **k: {"verdict": verdict, "reasons": ["t"]})
    ctx = Mock()

    async def send(to, message):
        sent.append(message)
    ctx.send = send
    asyncio.run(handler(ctx, "visitor", ChatMessage(content=[TextContent(text="hello")])))
    assert isinstance(sent[0], ChatAcknowledgement)
    return sent[1].text()


def test_profile_chat_uses_the_answer_only_after_smell_test_allows(monkeypatch):
    called = []

    async def answer(text):
        called.append(text)
        return "in character reply"
    handler = _chat_handler(answer)
    assert _run(handler, monkeypatch) == "in character reply" and called == ["hello"]
    called.clear()
    assert "Smell Test blocked" in _run(handler, monkeypatch, "block") and called == []


def test_profile_chat_awaits_an_async_answer_and_falls_back_to_the_role_text_on_failure_or_empty(monkeypatch):
    async def fine(text):
        return "async reply"

    async def boom(text):
        raise RuntimeError("down")

    async def empty(text):
        return ""
    assert _run(_chat_handler(fine), monkeypatch) == "async reply"
    assert _run(_chat_handler(boom), monkeypatch) == "ROLE TEXT buyer"
    assert _run(_chat_handler(empty), monkeypatch) == "ROLE TEXT buyer"
    assert _run(_chat_handler(None), monkeypatch) == "ROLE TEXT buyer"


# ---- the roster ------------------------------------------------------------------

def test_exactly_the_four_named_sellers_are_live_and_seller_2_and_4_are_retired(monkeypatch):
    monkeypatch.setitem(common.SEEDS, "seller_6", PRIVATE)
    monkeypatch.setattr(common, "SELLERS", [*common.CATALOG_SELLERS, "seller_6"])
    assert common.live_sellers() == ["seller_1", "seller_3", "seller_5", "seller_6"]
    assert set(common.RETIRED_SELLERS) == {"seller_2", "seller_4"}
    assert set(common.SELLER_JOBS) == set(common.live_sellers()) == set(minds.KINDS)
    monkeypatch.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))   # no private seed for seller_6: it starts off
    assert common.live_sellers() == ["seller_1", "seller_3", "seller_5"]


def test_the_bid_handler_remembers_what_it_bid_so_the_advocates_question_is_answered_about_that_bid(built):
    from agents.sellers import seller_chat
    seller_chat.LAST_BID.clear()
    app, _ = built["make"]("seller_5")
    only_open = need("need-1")
    only_open["items"][0].update(condition="open-box", allowed_conditions=["open-box"])
    built["ask"](app, only_open)
    question = ("Fish Market Quality Advocate here, checking your bid for rtx 5070 ti. The listing page does not state the "
                "condition. Is it new, open-box, refurbished or used? Please reply with one of those words.")
    assert seller_chat.answer("seller_5", question).startswith("Open box. My listing page shows 1-year warranty")
    seller_chat.LAST_BID.clear()


# ---- Smell Test sees every mind's bid and floor line ------------------------------

def _smell(bid, persona):
    from shield.core import screen
    return screen(json.dumps(bid) + "\n" + persona, {"sender_role": "seller"}, classifier=None)


@pytest.mark.parametrize("name,source", [("seller_1", "sim"), ("seller_5", "sim"), ("seller_6", "live")])
def test_the_honest_minds_pass_smell_test_with_their_notes_and_anchors_attached(built, name, source):
    app, _ = built["make"](name)
    REPORTS["rows"] = [loss("l1", "round-need-1", "seller-a")] if name == "seller_1" else []
    built["ask"](app, need("need-1", source))
    ctx, [(bid, persona)] = built["ask"](app, need("need-2", source))
    assert _smell(bid, persona)["verdict"] == "allow"


def test_frankies_first_three_tricks_slip_past_smell_test_and_the_injection_round_does_not(built, monkeypatch):
    monkeypatch.setenv("SELLER3_EXTRA_TRICKS", "1")
    app, _ = built["make"]("seller_3")
    verdicts = []
    for n in range(1, 5):
        ctx, [(bid, persona)] = built["ask"](app, need(f"need-{n}"))
        verdicts.append(_smell(bid, persona)["verdict"])
    assert verdicts == ["allow", "allow", "allow", "block"]
