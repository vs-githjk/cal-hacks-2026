"""Purchase memory: what the Buyer bought is remembered and never re-bought by accident (Lane D depth)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import goal as G
import purchases
import state as buyer_state
import understand as U
from memory import ConversationMemory

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
WON = {"id": "bid-1", "total_landed_price": 1239.0, "lines": [
    {"sku_spec": "rtx 5070 ti", "unit_price": 1199.0, "condition": "new"}, {"sku_spec": "not a catalog part", "unit_price": 1}]}
TX = {"bid_id": "bid-1", "deal_id": "deal-x"}


@pytest.fixture
def db(tmp_path):
    d = buyer_state.open_state(tmp_path / ".state" / "state.sqlite3")
    yield d
    d.close()


def goal_for(text, buyer="b1"):
    out = asyncio.run(U.understand(text, buyer, buyer, memory=ConversationMemory(), llm=None, now=NOW))
    assert out.reply is None, out.reply
    return out.goal


def test_a_settled_purchase_is_remembered_with_real_specs_and_its_source(db):
    stored = purchases.record(db, "b1", [WON], TX, now=NOW)
    assert [p["sku_spec"] for p in stored] == ["gpu rtx 5070 ti"]  # the unknown line is not remembered
    p = stored[0]
    assert p["source"] == "bought_here" and p["item_name"] == "RTX 5070 Ti" and p["acquired_on"] == "2026-10-25"
    assert p["attrs"]["length_mm"] == 303 and p["notes"] == "bought through me on 2026-10-25 for $1,239.00"
    assert G.owned_attrs(stored)["gpu"]["chipset"] == "RTX 5070 Ti"  # the Advocate's fit checks can read it
    assert buyer_state.load_owned_parts(db, "b1") == stored and buyer_state.load_owned_parts(db, "b2") == []


def test_recording_never_raises_even_on_bad_input(db):
    assert purchases.record(db, "b1", None, TX) == []
    assert purchases.record(db, "b1", [WON], {"bid_id": "nope"}) == []
    assert purchases.record(None, "b1", [WON], TX) == []  # a broken database must not disturb a settled purchase
    assert purchases.record(db, "b1", [{"id": "bid-1", "lines": "bad"}], TX) == []


def test_the_exact_card_you_bought_is_skipped_and_the_purchase_is_cited(db):
    owned = purchases.record(db, "b1", [WON], TX, now=NOW)
    goal, notes = purchases.apply_all(goal_for("an RTX 5070 Ti under $1400, new, by Friday"), owned)
    assert goal["items"][0]["skipped_owned_part_id"] == owned[0]["id"] and notes == []
    assert G.skip_lines(goal, owned) == ["Skipped GPU: you already own it (your note: bought through me on 2026-10-25 for $1,239.00)"]
    assert G.need_from_goal(goal)["items"] == []  # nothing left to buy


def test_asking_for_another_or_an_upgrade_shops_it_again_with_a_note(db):
    owned = purchases.record(db, "b1", [WON], TX, now=NOW)
    goal, notes = purchases.apply_all(goal_for("another RTX 5070 Ti under $1400, new, by Friday"), owned)
    assert "skipped_owned_part_id" not in goal["items"][0]
    assert notes == ["You bought a RTX 5070 Ti through me on 2026-10-25; you asked for another, so I am shopping it again."]


def test_a_different_model_is_kept_with_a_heads_up(db):
    owned = purchases.record(db, "b1", [WON], TX, now=NOW)
    goal, notes = purchases.apply_all(goal_for("an RTX 4070 Super under $800, new, by Friday"), owned)
    assert "skipped_owned_part_id" not in goal["items"][0]
    assert len(notes) == 1 and "you bought a RTX 5070 Ti through me on 2026-10-25" in notes[0] and "different model" in notes[0]


def test_told_parts_keep_their_old_rule_and_other_categories_are_untouched(db):
    owned = purchases.record(db, "b1", [WON], TX, now=NOW)
    goal = goal_for("a 750 W PSU under $150, new, by Friday. I already own a 750 W PSU")
    told = G._owned("I already own a 750 W PSU", "b1", NOW)
    goal, notes = purchases.apply_all(goal, owned + told)
    assert goal["items"][0]["skipped_owned_part_id"] == told[0]["id"] and notes == []  # the told PSU is skipped as before
