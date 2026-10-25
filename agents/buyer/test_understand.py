"""Goal understanding (Lane D depth): catalog-validated, one question at a time, remembers the conversation (RT-6, RT-15)."""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import catalog
import understand as U
from memory import ConversationMemory

NOW = datetime(2026, 10, 23, 21, 58, tzinfo=timezone.utc)  # a Friday


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def ask(text, sender="s1", mem=None, llm=None, now=NOW):
    return asyncio.run(U.understand(text, "buyer-" + sender, sender, memory=mem or ConversationMemory(), llm=llm, now=now))


def chat(messages, llm=None, mem=None, sender="s1"):
    mem = mem or ConversationMemory(clock=Clock())
    return [asyncio.run(U.understand(m, "buyer-" + sender, sender, memory=mem, llm=llm, now=NOW)) for m in messages]


def skus(out):
    return [i["sku_spec"] for i in out.goal["items"]]


# ---- catalog

def test_catalog_names_only_parts_we_hold():
    assert catalog.find_models("an RTX 5070 Ti please", "gpu") == ["rtx 5070 ti"]
    assert catalog.find_models("the 4070 super 12gb", "gpu") == ["rtx 4070 super 12gb"]
    assert catalog.find_models("RTX 4070", "gpu") == []  # no plain 4070 in the catalog: not a guess of the Super
    assert catalog.unknown_models("RTX 4090 for gaming", "gpu") == ["RTX 4090"]
    assert catalog.find_models("a 1000 W PSU", "psu") == [] and catalog.unknown_models("a 1000 W PSU", "psu") == ["1000W power supply"]
    assert catalog.find_models("a Ryzen 7 9700X", "cpu") == ["amd ryzen 7 9700x"]
    assert catalog.category_of("amd ryzen 7 9700x") == "cpu" and catalog.category_of("rtx 9090") is None
    assert not catalog.is_listed("amd ryzen 7 9700x") and catalog.is_listed("rtx 5070 ti")


# ---- regex reader (no key)

def test_regex_reads_the_filmed_goal_into_a_validated_goal():
    out = ask("find me an RTX 5070 Ti under $1,300, new, by Friday")
    assert out.reply is None and out.source == "regex"
    assert skus(out) == ["rtx 5070 ti"] and out.goal["cap"] == 1300 and out.goal["deadline"] == "2026-10-30T23:59:00Z"


def test_any_part_in_the_catalog_not_only_two_gpus():
    out = ask("an RX 7800 XT under $600, new, by Friday")
    assert skus(out) == ["rx 7800 xt 16gb"]
    out = ask("a 850 W PSU under $150 new by monday")
    assert skus(out) == ["psu 850w"]
    out = ask("a Ryzen 5 9600X under $250, new, by friday")
    assert skus(out) == ["amd ryzen 5 9600x"]
    assert "No seller on today's floor lists CPU yet" in " ".join(out.notes)


def test_a_bare_gpu_asks_which_card_instead_of_picking_one_rt15():
    out = ask("a new GPU under $800 by Friday")
    assert out.goal is None
    assert out.reply.count("?") == 1 or "Which graphics card?" in out.reply
    assert "1) RTX 4070 Super 12GB" in out.reply and "2) RX 7800 XT 16GB" in out.reply
    assert "5070" not in out.reply  # a card that cannot fit the budget is not offered


def test_unknown_model_is_never_turned_into_a_sku():
    out = ask("an RTX 4090 under $2000, new, by Friday")
    assert out.goal is None and "RTX 4090" in out.reply and "won't guess" in out.reply
    assert "1) RTX 5070 Ti" in out.reply and "3) RX 7800 XT 16GB" in out.reply


def test_a_budget_too_low_for_any_card_says_the_cheapest_price():
    out = ask("a gpu under $100, new, by friday")
    assert out.goal is None and "can't fit a graphics card" in out.reply and "What is your maximum budget?" in out.reply


def test_one_card_that_fits_is_chosen_and_said():
    out = ask("a gpu under $500, new, by friday")  # only the RX 7800 XT lists under $500 on today's floor
    assert out.reply is None and skus(out) == ["rx 7800 xt 16gb"]
    assert any("Only the RX 7800 XT 16GB fits" in n for n in out.notes)


def test_multi_part_build_asks_one_question_then_buys_what_the_floor_lists():
    first, second, third, fourth = chat(["a 1440p gaming PC under $1,800", "2", "new", "by Friday"])
    assert first.goal is None and "Which graphics card?" in first.reply and "1440p" in first.reply
    assert "1) RTX 5070 Ti" in first.reply
    assert second.goal is None and "new or open-box" in second.reply
    assert third.goal is None and "deadline" in third.reply
    assert skus(fourth) == ["rtx 4070 super 12gb", "psu 750w", "case"]
    assert fourth.goal["type"] == "build_by_date" and fourth.goal["cap"] == 1800
    joined = " ".join(fourth.notes)
    assert "no seller lists CPU, motherboard, RAM, SSD, cooler yet" in joined and "Budget guide for the whole build: Plan: GPU" in joined


def test_owned_parts_are_not_re_bought_in_a_build():
    out = ask("build me a 1440p PC with an RTX 4070 Super under $1,800, new, by Friday. I already own a 750 W PSU")
    assert skus(out) == ["rtx 4070 super 12gb", "psu 750w", "case"]  # the owned PSU is skipped later by apply_owned
    assert [o["sku_spec"] for o in out.owned] == ["psu 750w"]


def test_the_demo_goal_still_buys_only_the_gpu_it_names_after_one_answer():
    text = ("a new GPU for 1440p that fits my case and PSU, under $800, by Friday. "
            "I already own a 750 W PSU and a mid-tower with 330 mm GPU clearance")
    first, second = chat([text, "the 4070 super"])
    assert first.goal is None and "Which graphics card?" in first.reply
    assert skus(second) == ["rtx 4070 super 12gb"]  # fits my case/PSU and the owned parts add no lines
    assert {o["sku_spec"].split()[0] for o in second.owned} == {"psu", "case"}


# ---- multi-turn memory (RT-6): the audit's three-message conversation

def test_audit_conversation_three_messages_merge_into_one_goal():
    one, two, three = chat(["find me an RTX 5070 Ti under $1300", "new", "by Friday"])
    assert one.reply == "So far: RTX 5070 Ti, under $1,300. What condition do you want: new or open-box?"
    assert two.reply.endswith("When is your deadline? Give a date, weekday, or tomorrow.") and "new" in two.reply
    assert three.reply is None
    assert skus(three) == ["rtx 5070 ti"] and three.goal["cap"] == 1300
    assert three.goal["items"][0]["condition"] == "new" and three.goal["deadline"] == "2026-10-30T23:59:00Z"


def test_answers_fill_the_slot_that_was_asked_in_any_order():
    out = chat(["an RTX 5070 Ti", "$1,300", "new", "tomorrow"])
    assert [o.reply is None for o in out] == [False, False, False, True]
    assert out[-1].goal["cap"] == 1300 and out[-1].goal["deadline"] == "2026-10-24T23:59:00Z"


def test_a_bare_gpu_conversation_option_by_number_and_by_name():
    out = chat(["gpu", "$800", "1", "either", "friday"])
    assert out[-1].reply is None and skus(out[-1]) == ["rtx 4070 super 12gb"]
    assert out[-1].goal["items"][0]["allowed_conditions"] == ["new", "open-box"]
    out = chat(["gpu under $800 new by friday", "the rx 7800 xt"])
    assert skus(out[-1]) == ["rx 7800 xt 16gb"]


def test_memory_is_per_sender_and_expires_after_ten_minutes():
    clock = Clock()
    mem = ConversationMemory(clock=clock)
    asyncio.run(U.understand("an RTX 5070 Ti under $1300", "b-a", "alice", memory=mem, llm=None, now=NOW))
    other = asyncio.run(U.understand("new", "b-b", "bob", memory=mem, llm=None, now=NOW))
    assert "Which part are you after?" in other.reply  # bob never sees alice's goal
    clock.t += 599
    assert asyncio.run(U.understand("new", "b-a", "alice", memory=mem, llm=None, now=NOW)).reply.endswith(
        "Give a date, weekday, or tomorrow.")
    clock.t += 601  # ten minutes after the last write: gone
    gone = asyncio.run(U.understand("by Friday", "b-a", "alice", memory=mem, llm=None, now=NOW))
    assert "Which part are you after?" in gone.reply


def test_a_message_about_a_different_part_starts_a_fresh_goal_and_cancel_clears():
    mem = ConversationMemory(clock=Clock())
    asyncio.run(U.understand("an RTX 5070 Ti under $1300", "b", "s", memory=mem, llm=None, now=NOW))
    out = asyncio.run(U.understand("a 750 W power supply under $100, new, by Friday", "b", "s", memory=mem, llm=None, now=NOW))
    assert skus(out) == ["psu 750w"] and out.goal["cap"] == 100
    asyncio.run(U.understand("an RTX 5070 Ti under $1300", "b", "s", memory=mem, llm=None, now=NOW))
    assert "dropped" in asyncio.run(U.understand("never mind", "b", "s", memory=mem, llm=None, now=NOW)).reply
    assert mem.get("s") is None


def test_a_past_deadline_is_refused_and_asked_again():
    out = chat(["an RTX 5070 Ti under $1300, new, by 2026-10-01", "by Friday"])
    assert "in the past" in out[0].reply and out[0].goal is None
    assert skus(out[1]) == ["rtx 5070 ti"]


# ---- Claude reader (mocked): validated against the catalog, never trusted

def fake(payload):
    return lambda text, ctx: payload


def test_claude_reads_free_text_and_the_result_is_validated():
    payload = {"build": True, "parts": [{"part": "gpu", "model": "5070 ti"}], "use_case": "1440p", "budget_usd": 1800,
               "conditions": ["new"], "deadline": "friday", "option": None}
    out = ask("I want a sweet 1440p rig around 1800 bucks, brand new, by friday please, with the 5070 ti", llm=fake(payload))
    assert out.reply is None and out.source == "claude"
    assert skus(out) == ["rtx 5070 ti", "psu 750w", "case"] and out.goal["cap"] == 1800
    assert out.goal["deadline"] == "2026-10-30T23:59:00Z" and out.goal["items"][0]["condition"] == "new"


def test_claude_cannot_invent_a_sku_or_a_budget():
    payload = {"build": False, "parts": [{"part": "gpu", "model": "RTX 9090 Ti"}], "budget_usd": 777,
               "conditions": ["new"], "deadline": "friday"}
    out = ask("some monster card, new, friday", llm=fake(payload))
    assert out.goal is None and "RTX 9090 TI" in out.reply.upper() and "won't guess" in out.reply
    out = ask("an RTX 5070 Ti, new, friday", llm=fake(dict(payload, parts=[{"part": "gpu", "model": "5070 ti"}])))
    assert out.goal is None and out.reply.endswith("What is your maximum budget?")  # 777 was never typed: ignored


def test_claude_cannot_decide_a_date_or_a_typed_number_the_code_disagrees_with():
    payload = {"parts": [{"part": "gpu", "model": "5070 ti"}], "budget_usd": 9999, "conditions": ["new"], "deadline": "2020-01-01"}
    out = ask("an RTX 5070 Ti under $1300, new, by Friday", llm=fake(payload))
    assert out.goal["cap"] == 1300 and out.goal["deadline"] == "2026-10-30T23:59:00Z"  # typed words beat the model


@pytest.mark.parametrize("llm", [
    lambda t, c: (_ for _ in ()).throw(TimeoutError("slow")),
    lambda t, c: None,
    lambda t, c: "not json",
    lambda t, c: {"parts": "gpu", "budget_usd": "lots", "conditions": 5},
    lambda t, c: {"parts": [{"part": "toaster", "model": "x"}], "conditions": ["mint"]},
])
def test_any_llm_failure_falls_back_to_the_regex_reader(llm):
    out = ask("an RTX 5070 Ti under $1,300, new, by Friday", llm=llm)
    assert out.reply is None and out.source == "regex" and skus(out) == ["rtx 5070 ti"]


def test_a_slow_llm_is_cut_off_at_the_timeout(monkeypatch):
    monkeypatch.setattr(U, "TIMEOUT_S", 0.05)
    async def go():
        started = time.monotonic()  # inside the loop: asyncio.run itself waits for the worker thread at shutdown
        out = await U.understand("an RTX 5070 Ti under $1,300, new, by Friday", "b", "s", memory=ConversationMemory(),
                                 llm=lambda t, c: time.sleep(0.5) or {"parts": []}, now=NOW)
        return time.monotonic() - started, out
    elapsed, out = asyncio.run(go())
    assert elapsed < 0.4 and out.source == "regex" and skus(out) == ["rtx 5070 ti"]


def test_claude_reads_an_answer_in_the_context_of_the_question():
    seen = []

    def llm(text, ctx):
        seen.append(ctx)
        return {"conditions": ["new"]} if text == "yeah sealed in box" else {"parts": [{"part": "gpu", "model": "5070 ti"}], "budget_usd": 1300}
    one, two = chat(["rtx 5070 ti 1300 max", "yeah sealed in box"], llm=llm)
    assert two.reply.endswith("Give a date, weekday, or tomorrow.") and "new" in two.reply
    assert seen[1]["pending"] == {"slot": "condition", "options": []} and seen[1]["so_far"]["cap"] == 1300


def test_claude_call_is_bounded_and_off_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert U.claude_llm("x", {}) is None
    calls = {}

    class Messages:
        def create(self, **kw):
            calls["create"] = kw
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='```json\n{"parts": []}\n```')])

    class Client:
        def __init__(self, **kw):
            calls["init"] = kw
            self.messages = Messages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=Client))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("BUYER_UNDERSTAND_LLM", "1")
    assert U.claude_llm("an rtx", {"today": "2026-10-23"}) == {"parts": []}
    assert calls["init"]["timeout"] == 6.0 and calls["init"]["max_retries"] == 0
    assert calls["create"]["model"] == "claude-haiku-5-5"
    assert json.loads(calls["create"]["messages"][0]["content"])["message"] == "an rtx"
