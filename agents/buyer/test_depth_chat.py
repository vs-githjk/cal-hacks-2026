"""The depth features wired into the Buyer's chat handlers (understanding, memory, round summary, purchase memory)."""
import asyncio
import json
import time

import pytest
from uagents_core.contrib.protocols.payment import CompletePayment

import state
from test_recovery import Context, buyer as recovery_buyer, card  # noqa: F401  (fixture)
from test_runtime_checkout import charged_transaction, runtime  # noqa: F401  (fixture)


def sent_to(ctx, who):
    return [m.text() for to, m in ctx.sent if to == who and hasattr(m, "text")]


def test_three_message_asi_conversation_ends_in_a_running_round(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND.clear()
    for text in ("find me an RTX 5070 Ti under $1300", "new", "by Friday"):
        asyncio.run(buyer.handle_text(ctx, "owner", text))
    replies = sent_to(ctx, "owner")
    assert replies[0] == "So far: RTX 5070 Ti, under $1,300. What condition do you want: new or open-box?"
    assert replies[1].endswith("When is your deadline? Give a date, weekday, or tomorrow.")
    assert buyer.ROUND["phase"] == "bidding" and buyer.ROUND["owner"] == "owner"
    assert [i["sku_spec"] for i in buyer.ROUND["need"]["items"]] == ["rtx 5070 ti"]
    assert buyer.ROUND["goal"]["cap"] == 1300 and buyer.ROUND["need"]["spend_limit"] == 1300
    assert "Goal: under $1300" in replies[2]


def test_a_bare_gpu_gets_one_question_and_no_round(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND.clear()
    asyncio.run(buyer.handle_text(ctx, "owner", "I need a GPU under $800, new, by Friday"))
    assert "Which graphics card?" in sent_to(ctx, "owner")[0] and "1) RTX 4070 Super 12GB" in sent_to(ctx, "owner")[0]
    assert not buyer.ROUND.get("need") and buyer.ROUND.get("phase") is None


def test_the_round_ends_with_a_plain_sourced_summary(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND.update(owner_context=ctx, owner_session=ctx.session, phase="advice", deadline=time.time() + 30)
    veto = card(recommendation="veto", warnings=[{"kind": "fit", "text": "Too long for your case.",
                                                  "source_url": "https://www.example.test/spec", "dollar_impact": 0}])
    asyncio.run(buyer.on_advice(ctx, buyer.common.address("advocate"), buyer.common.AdviceReply(cards_json=json.dumps([veto]))))
    asyncio.run(buyer._finish_market_round(ctx))
    text = ctx.owner_text()
    assert "Round summary: 1 of" in text and "The advocate vetoed Seller: it would not fit your build (source: example.test)." in text
    assert "Seller won on landed price at $582.00" in text
    assert "bid-1" not in text.split("Round summary:")[1].split("\n")[0]  # no ids in the summary line


def test_a_settled_purchase_is_remembered_and_not_bought_twice(runtime):  # noqa: F811
    from test_runtime_checkout import Context as RtContext
    buyer, db = runtime
    tx, _ = charged_transaction(buyer, db)
    buyer.ROUND["bids"] = [{"id": "bid-1", "total_landed_price": 582.0,
                            "lines": [{"sku_spec": "rtx 4070 super 12gb", "unit_price": 560.0, "condition": "new"}]}]
    asyncio.run(buyer.on_complete(RtContext(), tx["mandate"]["payee"], CompletePayment(transaction_id="ch_simulated_runtime")))
    assert [(p["sku_spec"], p["source"]) for p in state.load_owned_parts(db, "owner")] == [("gpu rtx 4070 super 12gb", "bought_here")]
    ctx = RtContext()
    asyncio.run(buyer.handle_text(ctx, "owner", "an RTX 4070 Super under $800, new, by Friday"))
    reply = "\n".join(m.text() for _, m in ctx.sent if hasattr(m, "text"))
    assert "Skipped GPU: you already own it (your note: bought through me on" in reply
    assert "You already own everything on that list. Nothing to buy." in reply


def _summary_line(ctx):
    return next(line for line in ctx.owner_text().split("\n") if line.startswith("Round summary:"))


def _finish(buyer, ctx, cards):
    buyer.ROUND.update(owner_context=ctx, owner_session=ctx.session, phase="advice", deadline=time.time() + 30,
                       quoted_at=time.time())
    asyncio.run(buyer.on_advice(ctx, buyer.common.address("advocate"), buyer.common.AdviceReply(cards_json=json.dumps(cards))))
    asyncio.run(buyer._finish_market_round(ctx))
    return _summary_line(ctx)


def test_next_step_is_the_call_only_when_the_buyer_will_really_order(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    line = _finish(buyer, ctx, [card()])
    assert line.endswith("Next: I get a fresh quote and then call your phone for the approval code. "
                         "Nothing is paid unless you approve on that call.")


def test_a_vetoed_winner_is_not_followed_by_a_promised_call(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    veto = card(recommendation="veto", warnings=[{"kind": "fit", "text": "x", "source_url": "https://a.example/s", "dollar_impact": 0}])
    line = _finish(buyer, ctx, [veto])
    assert "call your phone" not in line and "fresh quote" not in line
    assert "Next: I will not order this bid because it is unreviewed or vetoed. Nothing was ordered; reply CANCEL" in line


def test_a_seller_that_fails_the_eligibility_check_is_not_followed_by_a_promised_call(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND["seller_checks"] = {"seller_1": {"eligible": False, "signal": None, "reason": "not eligible"}}
    line = _finish(buyer, ctx, [card()])
    assert "call your phone" not in line
    assert "Next: I will not order any of these bids" in line and "failed round 1 of 3; I run a fresh round in 60 seconds" in line


def test_the_last_failed_round_says_the_goal_is_paused_not_that_it_hunts_on(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND.update(attempts=2, seller_checks={"seller_1": {"eligible": False, "signal": None, "reason": "no"}})
    line = _finish(buyer, ctx, [card()])
    assert "failed round 3 of 3, so I paused this goal; send it again to restart" in line
    assert "keep hunting" not in line and "until your deadline" not in line


def test_an_over_cap_winner_is_not_followed_by_a_promised_call(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND["need"]["spend_limit"] = 500
    line = _finish(buyer, ctx, [card()])
    assert "call your phone" not in line and "Next: the best eligible bid is over your cap. Nothing was ordered." in line
