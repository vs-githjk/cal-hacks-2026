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
        asyncio.run(buyer.handle_text(ctx, "carol", text))
    replies = sent_to(ctx, "carol")
    assert replies[0] == "So far: RTX 5070 Ti, under $1,300. What condition do you want: new or open-box?"
    assert replies[1].endswith("When is your deadline? Give a date, weekday, or tomorrow.")
    assert buyer.ROUND["phase"] == "bidding" and buyer.ROUND["owner"] == "carol"
    assert [i["sku_spec"] for i in buyer.ROUND["need"]["items"]] == ["rtx 5070 ti"]
    assert buyer.ROUND["goal"]["cap"] == 1300 and buyer.ROUND["need"]["spend_limit"] == 1300
    assert "Goal: under $1300" in replies[2]


def test_a_bare_gpu_gets_one_question_and_no_round(recovery_buyer):
    buyer, ctx = recovery_buyer, Context()
    buyer.ROUND.clear()
    asyncio.run(buyer.handle_text(ctx, "dave", "I need a GPU under $800, new, by Friday"))
    assert "Which graphics card?" in sent_to(ctx, "dave")[0] and "1) RTX 4070 Super 12GB" in sent_to(ctx, "dave")[0]
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
