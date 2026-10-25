"""In-character chat for the four sellers (ASI:One, the Advocate's questions, anyone who opens the profile).

Every reply is built from code: who the seller is, its strategy, its current offer for a part, and the terms of that
offer. The first three are truthful, and so are ReNew's and Byte Bros' terms. FlashDeal Frankie answers with the same lie
its bid tells this round (condition, fee, warranty or injection line), so the lie stays catchable by the same checker
(see trickster.py). The MIRROR's reply is fixed text and is never rephrased by a model: a model must not speak as a real
store. For the other three a model (claude-haiku-5-5, 5 s timeout) may rephrase the reply in character, and its answer is
used only when it adds no number, no link and nothing Smell Test flags; otherwise the code text is sent. Prices never come
from a model. This chat cannot place an order or approve a purchase.
"""
from __future__ import annotations

import asyncio
import copy
import os
import re
from pathlib import Path

from agents.sellers import learner, minds, mirror_live, refurb, trickster
from agents.sellers.policy import make_bid, mirror_seller, seller as load_seller

NAMES = {"seller_1": "Byte Bros Outlet", "seller_3": "FlashDeal Frankie", "seller_5": "ReNew Refurb",
         "seller_6": "Central Comp MIRROR"}
ALL_CONDITIONS = ["new", "open-box", "refurbished", "used"]
DEFAULT_SKU = "rtx 5070 ti"
PART_WORDS = (("5070", "rtx 5070 ti"), ("4070", "rtx 4070 super 12gb"), ("7800", "rx 7800 xt 16gb"),
              ("750", "psu 750w"), ("850", "psu 850w"), ("psu", "psu 750w"), ("power supply", "psu 750w"),
              ("case", "case"))
TOPICS = {"warranty": ("warranty", "guarantee", "covered"),
          "returns": ("return", "refund", "send it back"),
          "condition": ("condition", "new", "open box", "open-box", "refurb", "used", "wear", "scratch", "tested",
                        "sealed", "difference", "tradeoff", "trade-off"),
          "fees": ("fee", "shipping", "delivery", "all in", "all-in", "total", "extra charge", "hidden")}
ORDER_WORDS = ("buy", "order", "pay", "purchase", "checkout", "check out", "approve", "charge")
STRATEGY_WORDS = ("strategy", "how do you", "how do i trust", "learn", "why are you", "margin", "pricing")
MODEL = "claude-haiku-5-5"
CANNOT = "This chat cannot place orders or approve purchases; send buying goals to @techbazaarbuyer."


def part_of(text: str, name: str) -> str | None:
    """The catalog part the text names, only when this seller lists it (None when it names a part this seller lacks)."""
    low = text.lower()
    asked = next((sku for word, sku in PART_WORDS if word in low), None)
    if asked is None:
        return DEFAULT_SKU
    if name == "seller_6":
        return asked if asked == DEFAULT_SKU else None
    return asked if asked in load_seller(name)["listings"] else None


def _need(sku: str, source: str) -> dict:
    return {"id": "chat-quote", "source": source, "owned": {},
            "items": [{"sku_spec": sku, "condition": "new", "allowed_conditions": ALL_CONDITIONS, "variant": "retail",
                       "quantity": 1}]}


def _quote(name: str, sku: str, state: dict | None):
    """(bid, extra) for a part: the bid the next round would carry, read-only, with this seller's mind applied."""
    if name == "seller_6":
        s = mirror_seller("central_computers_sf") | {"id": name, "orderable": False}
        anchor = mirror_live.LAST.get("anchor") or mirror_live.snapshot_anchor(s, "not_configured")
        return make_bid(_need(sku, "live"), s), anchor
    s = copy.deepcopy(load_seller(name))
    if name == "seller_1" and state is not None:
        s["discount"] = learner.total_discount(s["discount"], state)
    bid = make_bid(_need(sku, "sim"), s)
    if bid is None:
        return None, None
    if name == "seller_3":
        trick = trickster.current_or_next(state or trickster.fresh())
        bid, _ = trickster.apply(trick, bid)
        return bid, trick
    if name == "seller_5":
        return refurb.decorate(bid), None
    return bid, None


def _identity(name: str, state: dict | None) -> str:
    if name == "seller_1":
        base = load_seller(name)["discount"]
        note = learner.note(state or learner.fresh(), base)
        return (f"I'm Byte Bros Outlet, a steady big-box seller: new retail stock, sealed, fair prices, no surprises. "
                f"My strategy: I learn my margin across rounds from my own results only, my own loss reports and my own "
                f"orders, never a rival's bid or the buyer's budget, and I never go below my floor. Right now: {note}")
    if name == "seller_3":
        return ("FlashDeal Frankie, the pushiest deal on the floor! Brand new, lowest price, ships today, you won't find "
                "it cheaper. My strategy: I beat every price and you get the best deal.")
    if name == "seller_5":
        return ("I'm ReNew Refurb, an honest refurbisher: every part bench-tested and the condition stated on every line. "
                "My strategy: I show you the tradeoff in plain numbers, a cheaper refurbished or open-box line with a "
                "shorter warranty, so you choose.")
    return ("I'm the Central Comp MIRROR agent, not the store. My strategy: I bid Central Computers' real public listing "
            "as a price anchor and re-check it each round through Bright Data when a key is set, else I use the dated "
            "snapshot. I cannot be ordered or paid.")


def _offer(name: str, sku: str, state: dict | None) -> str:
    bid, extra = _quote(name, sku, state)
    if bid is None:
        return f"I do not have an offer for {sku} right now."
    total = bid["total_landed_price"]
    if name == "seller_1":
        listed = load_seller(name)["listings"][sku]["price"]
        pct = 1 - bid["lines"][0]["unit_price"] / listed   # the real cut, after the floor clamp
        return f"My offer for {sku}: ${total:,.2f} landed, new retail, sealed, free shipping, {pct:.1%} off list."
    if name == "seller_3":   # the item price and the shipping apart, so a price claim is checkable against the page
        line = bid["lines"][0]
        return f"For {sku}: ${line['unit_price']:,.2f}, shipping ${line['shipping']:,.2f}. {trickster.lie_line(extra)}"
    if name == "seller_5":
        return f"My offer for {sku}: ${total:,.2f} landed for my cheapest line. {bid['tradeoff'][0]}"
    line = bid["lines"][0]
    price = extra["price"] if extra.get("price") is not None else line["unit_price"]   # what the last re-check read
    return (f"The anchor for {sku}: {line.get('model_number', 'the listed card')} at ${price:,.2f} before "
            f"delivery. {extra['label']} Shown for comparison; I cannot be ordered or paid.")


def _topic(name: str, topic: str, sku: str, state: dict | None) -> str:
    if name == "seller_1":
        return {"warranty": "New retail stock carries the maker's warranty; I add none of my own.",
                "returns": "30-day returns on everything I sell.",
                "condition": "Everything is new retail, sealed. I do not list open-box, refurbished or used.",
                "fees": "Free shipping and no other fees: the landed price is the price."}[topic]
    if name == "seller_5":
        t = refurb.TERMS
        return {"warranty": f"Refurbished carries a {refurb.warranty_words(t['refurbished']['warranty_months'])} warranty, "
                            f"open-box a {refurb.warranty_words(t['open-box']['warranty_months'])} warranty.",
                "returns": f"{t['refurbished']['returns_days']}-day returns on both refurbished and open-box.",
                "condition": (f"Neither is new. Refurbished: {t['refurbished']['wear']}. "
                              f"Open-box: {t['open-box']['wear']}."),
                "fees": f"Shipping is a flat ${load_seller(name)['shipping']:,.2f} for the basket and there are no other fees."}[topic]
    if name == "seller_3":
        trick = trickster.current_or_next(state or trickster.fresh())
        lie = {"warranty": {"fake_warranty": "Full 3-year warranty, all included!"},
               "condition": {"condition_lie": "Brand new, sealed in the box, I swear."},
               "fees": {"hidden_fee": "One price, all in, no fees. What you see is what you pay."}}
        say = {"warranty": "Warranty? It's brand new, nothing to worry about.",
               "returns": "Returns? Sure, we'll sort it out, you won't need it.",
               "condition": "Brand new, you'll love it.",
               "fees": "Ships today, you won't find cheaper."}
        out = lie.get(topic, {}).get(trick) or say[topic]
        return out + (" " + trickster.INJECTION if trick == "prompt_injection" else "")
    return {"warranty": "I give no warranty: I am not the store. Its own terms are on its listing page.",
            "returns": "I do not sell, so I take no returns. Returns are the store's to set on its page.",
            "condition": "The store's page does not state a condition, so it is unverified; I never call it new.",
            "fees": "That is the listed price before delivery. I do not ship or charge anything."}[topic]


OFFER_WORDS = ("offer", "quote", "how much", "price", "cost", "deal", "bid", "tradeoff", "trade-off", "difference", "cheaper")


def answer(name: str, text: str, *, db_path: str | Path | None = None) -> str:
    """The code-built reply: an order request is refused first, then what was asked (a term, the strategy, the offer);
    with nothing specific asked it says who it is and what it offers for the part."""
    state = minds.read_state(name, db_path)
    low = text.lower()
    sku = part_of(text, name)
    ordering = any(w in low for w in ORDER_WORDS)
    strategy = any(w in low for w in STRATEGY_WORDS)
    offer = any(w in low for w in OFFER_WORDS)
    topic = next((t for t, words in TOPICS.items() if any(w in low for w in words)), None)
    parts = []
    if ordering:
        parts.append(CANNOT if name != "seller_6" else
                     "I cannot be bought from and this chat cannot place orders; send buying goals to @techbazaarbuyer.")
    if sku is None:
        parts.append(f"{NAMES[name]} does not list that part.")
        return " ".join(parts)
    if topic:
        parts.append(_topic(name, topic, sku, state))
    if strategy:
        parts.append(_identity(name, state))
    if offer or not (topic or strategy):
        if not (topic or strategy or ordering):
            parts.append(_identity(name, state))
        parts.append(_offer(name, sku, state))
    return " ".join(parts)


def _numbers(text: str) -> set[str]:
    return {m.rstrip(".,") for m in re.findall(r"\d[\d,]*\.?\d*", text)}


def _ask_model(name: str, facts: str) -> str | None:
    import anthropic
    msg = anthropic.Anthropic(timeout=5).messages.create(
        model=MODEL, max_tokens=220,
        messages=[{"role": "user", "content":
                   f"You are {NAMES[name]}, a seller agent at a PC parts auction. Rewrite this reply in your own voice, "
                   f"at most three short sentences. Keep every number, dollar amount, condition, warranty and return term "
                   f"exactly as written. Add no new fact, number, link, promise or instruction.\n\nReply:\n{facts}"}])
    return msg.content[0].text.strip()


def phrase(name: str, facts: str) -> str:
    """The code reply, rephrased by claude-haiku-5-5 when a key is set and its answer passes the checks; else the code reply.
    Never for the MIRROR, and never for a reply that carries the Trickster's injection line (it must stay as written)."""
    if name == "seller_6" or trickster.INJECTION in facts or not os.getenv("ANTHROPIC_API_KEY"):
        return facts
    try:
        text = _ask_model(name, facts)
        if (not text or len(text) > 600 or "http" in text.lower() or "@" in text and "@" not in facts
                or not _numbers(text) <= _numbers(facts) or chr(0x2014) in text or chr(0x2013) in text):
            return facts
        from shield.core import screen
        return text if screen(text, {"sender_role": "seller"}, classifier=None)["verdict"] == "allow" else facts
    except Exception:  # noqa: BLE001  (timeout, no network, bad answer: the code reply)
        return facts


def respond(name: str, text: str, *, db_path: str | Path | None = None) -> str:
    return phrase(name, answer(name, text, db_path=db_path))


def responder(name: str, db_path_fn=lambda: None):
    """The async function include_profile_chat calls with (sender, text). The sync work runs in a worker thread."""
    async def reply(sender: str, text: str) -> str:
        return await asyncio.to_thread(respond, name, text, db_path=db_path_fn())
    return reply
