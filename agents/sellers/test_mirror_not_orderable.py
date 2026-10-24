"""#333 item 1, end to end through the buyer: a Central Computers (MIRROR, never joined) bid that is the cheapest and
passes every other check yields no winner, no approval, no mandate and no order. Each guard is tested on its own,
with the store given a wired address (as it would have once seller_6 exists), so none of them holds by accident."""
import asyncio
import pytest
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from buyer.test_runtime_checkout import Context, ready_for_requote, reviewed_card, runtime  # noqa: F401
from data.mirror import not_partners
from policy import make_bid, mirror_seller

CC = "central_computers_sf"
LABEL = not_partners.SELLERS[CC]


@pytest.fixture(params=[CC, "seller_6"])
def supplier(request):
    """The store's own id, and seller_6, the uAgent that bids its listings (#342)."""
    return request.param


def _cc_bid(need, supplier):
    if supplier == CC:
        bid = make_bid({**need, "source": "live"}, mirror_seller(CC, 305))
    else:
        from agents.sellers import seller_agent
        bid = make_bid({**need, "source": "live"}, seller_agent._mirror_for(supplier, {"owned": {"case": {
            "max_gpu_length_mm": 305}}}))
    assert bid and bid["origin"] == "MIRROR" and bid["supplier_id"] == supplier
    return bid


def _wire_cc(buyer, monkeypatch, supplier):
    """Give the seller an address (seller_6 has one once its seed is set), so a KeyError cannot save us."""
    real = buyer.common.address
    monkeypatch.setattr(buyer.common, "address", lambda name: "agent1qcentralcomputerssf" if name == supplier
                        else real(name))


def _cc_round(buyer, supplier, recommendation="caution"):
    ready_for_requote(buyer)
    need = buyer.ROUND["need"]
    need["items"][0]["sku_spec"] = "rtx 5070 ti"
    need["spend_limit"] = 1500.0  # the bid is inside the cap, so only the not-orderable rule can stop it
    bid = dict(_cc_bid(need, supplier), candidate_binding_hash="c" * 64, market_binding_hash="c" * 64,
               expires_at=(buyer.business_now() + timedelta(seconds=600)).isoformat())  # a valid fresh quote
    card = dict(reviewed_card(bid_id=bid["id"]), recommendation=recommendation)
    buyer.ROUND.update(bids=[bid], cards={bid["id"]: card}, seller_checks={supplier: {"eligible": True}},
                       original_offer=dict(bid), candidate_hashes={bid["id"]: "c" * 64},
                       market_winner=bid, quoted_at=buyer.business_now().timestamp())
    return bid


def _owner_text(ctx):
    return "\n".join(m.text() for _to, m in ctx.sent if hasattr(m, "text"))


def test_conclude_names_no_winner_for_a_mirror_bid_and_shows_its_label(runtime, monkeypatch, supplier):
    buyer, _db = runtime
    _wire_cc(buyer, monkeypatch, supplier)
    _cc_round(buyer, supplier)  # even if a market picked it and the advocate only cautioned
    ctx = Context()
    buyer.ROUND.update(phase="advice", owner_context=ctx, owner_session=ctx.session)
    asyncio.run(buyer.conclude(ctx, reviewed=True))
    text = _owner_text(ctx)
    assert LABEL in text and not_partners.NOT_ORDERABLE in text and "Nothing ordered" in text
    assert "Deal found" not in text and "APPROVE" not in text
    assert buyer.ROUND["goal"]["state"] != "HOLD_FOR_CALL" and buyer.ROUND["phase"] != "decided"


def test_eligible_for_order_and_approve_refuse_a_mirror_bid(runtime, monkeypatch, supplier):
    buyer, _db = runtime
    _wire_cc(buyer, monkeypatch, supplier)
    _cc_round(buyer, supplier, recommendation="buy")
    assert buyer.eligible_for_order(1) is False
    ctx = Context()
    buyer.ROUND.update(phase="decided", transaction=None, owner_context=ctx, owner_session=ctx.session)
    asyncio.run(buyer.approve(ctx, 1, sender="owner"))
    assert not any(isinstance(m, buyer.common.BidRequest) for _to, m in ctx.sent)
    assert buyer.ROUND["phase"] == "decided"


def test_requote_never_makes_a_mandate_for_a_mirror_bid(runtime, monkeypatch, supplier):
    buyer, db = runtime
    _wire_cc(buyer, monkeypatch, supplier)
    bid = _cc_round(buyer, supplier, recommendation="buy")
    ctx = Context()
    asyncio.run(buyer.on_requote(ctx, dict(bid)))
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert not buyer.ROUND.get("transaction") and not buyer.ROUND.get("order")
    assert not buyer.MARKET_BUYER.create_mandate.called
    assert not_partners.NOT_ORDERABLE in _owner_text(ctx)
    assert not any(isinstance(m, buyer.common.OrderPlaced) for _to, m in ctx.sent)


def test_the_sim_requote_still_makes_its_mandate(runtime):
    buyer, db = runtime
    ready_for_requote(buyer)
    asyncio.run(buyer.on_requote(Context(), dict(buyer.ROUND["bids"][0])))
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
