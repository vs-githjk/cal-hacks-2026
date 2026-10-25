"""Goal understanding for the Buyer chat: free text (and the answers that follow it) -> a validated Goal, or ONE question.

The Buyer's money path stays deterministic. Claude (a fast model, behind a 6 second timeout) may only READ the
owner's words into a draft: which parts, which models, a budget, a condition, a deadline. Everything it says is then
checked in code against the catalog (catalog.py) and the Goal schema:
  * a model name becomes a SKU only if the catalog holds it; anything else is asked about, never invented;
  * a budget must be a number the owner actually typed;
  * a deadline is resolved by goal._deadline_day, not by the model;
  * with no key, a timeout, an error or bad JSON, the regex reader below produces the same draft shape.
When something is missing or ambiguous, it asks ONE question (2-3 concrete options for a model) and remembers the
unfinished goal for ten minutes (memory.py), so "new" or "$1,300" or "2" is merged into the goal they belong to.

An LLM never decides a payment, approval, veto or ranking. This module never touches those.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import catalog
import common
import goal as G
from memory import MEMORY, ConversationMemory

MODEL = os.environ.get("BUYER_UNDERSTAND_MODEL", "claude-haiku-5-5")
TIMEOUT_S = 6.0
CONDITIONS = ("new", "open-box", "refurbished")
USE_CASES = r"1080p|1440p|2160p|4k|ultrawide"
BUILD_RX = re.compile(r"\b(?:build|rig)\b|\b(?:gaming|new|complete|whole|full|entire)\s+(?:pc|computer|desktop|rig)\b"
                      r"|\b(?:pc|computer|desktop)\s+(?:build|under|for)\b", re.I)
FIT_CLAUSE = re.compile(r"\b(?:fits?|fitting|compatible with|works? with)\s+(?:my|the|your)\s+[^,.;]*", re.I)
CANCEL_RX = re.compile(r"^\s*(?:cancel|never ?mind|forget it|start over|reset)\s*[.!]?\s*$", re.I)
ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3}
ORDER = ("gpu", "psu", "case", "cpu", "motherboard", "memory", "storage", "cooler")


@dataclass
class Outcome:
    """reply is set when there is no goal yet (a question, or why nothing could be read). Otherwise goal/owned are set."""
    reply: str | None = None
    goal: dict | None = None
    owned: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    source: str = "regex"  # who read the words: "claude" or "regex"


def new_draft() -> dict:
    return {"cats": [], "build": False, "models": {}, "unknown": {}, "ambiguous": {}, "use_case": None, "cap": None,
            "conditions": None, "day": None, "day_error": None, "texts": [], "pending": None, "notes": []}


# ---------------------------------------------------------------- the regex reader (also the fallback)

def _conditions(text: str, pending: dict | None = None) -> list[str] | None:
    found = []
    if re.search(r"\bnew\b", text, re.I):
        found.append("new")
    if re.search(r"\bopen[- ]box\b", text, re.I):
        found.append("open-box")
    if re.search(r"\brefurb(?:ished)?\b", text, re.I):
        found.append("refurbished")
    if not found and pending and pending.get("slot") == "condition" and re.search(r"\b(?:either|any|both|doesn.?t matter)\b", text, re.I):
        found = ["new", "open-box"]
    return found or None


def _bare_amount(text: str) -> float | None:
    m = re.fullmatch(r"\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:dollars|usd|bucks)?\s*[.!]?\s*", text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _option_index(text: str, count: int) -> int | None:
    m = re.fullmatch(r"\s*(?:option\s*|number\s*|no\.?\s*|#)?([1-9])\s*[.)!]?\s*", text, re.I)
    if m:
        n = int(m.group(1))
    else:
        w = re.fullmatch(r"\s*(?:the\s+)?(first|second|third|1st|2nd|3rd)(?:\s+one)?\s*[.!]?\s*", text, re.I)
        n = ORDINALS[w.group(1).lower()] if w else 0
    return n - 1 if 1 <= n <= count else None


def _day(text: str, now: datetime) -> tuple[str | None, str | None]:
    try:
        d = G._deadline_day(text, now)
    except ValueError as e:
        return None, str(e)
    return (d.isoformat() if d else None), None


def _subject_text(text: str) -> str:
    """The words that name what to buy: not the owner's own parts and not 'fits my case and PSU'."""
    text = FIT_CLAUSE.sub(" ", text)
    text = re.sub(r"\bin case\b", " ", text, flags=re.I)
    keep = [s for s in G._sentences(text)
            if not re.search(G.OWN_VERB, s, re.I) or re.search(r"\b(?:upgrade|replace)\w*\b", s, re.I)]
    return " ".join(keep)


def _models_into(d: dict, subject: str) -> None:
    for cat in catalog.CATEGORIES:
        found = catalog.find_models(subject, cat)
        if len(found) == 1:
            d["models"][cat] = found[0]
        elif len(found) > 1:
            d["ambiguous"][cat] = found
        miss = catalog.unknown_models(subject, cat)
        if miss:
            d["unknown"][cat] = miss
        if cat not in d["cats"] and (found or miss):
            d["cats"].append(cat)


def regex_draft(text: str, now: datetime, pending: dict | None = None) -> dict:
    d = new_draft()
    d["texts"] = [text]
    subject = _subject_text(text)
    d["build"] = bool(BUILD_RX.search(subject))
    for cat in catalog.CATEGORIES:
        if re.search(rf"\b(?:{catalog.WORDS[cat]})\b", subject, re.I):
            d["cats"].append(cat)
    _models_into(d, subject)
    if m := re.search(rf"\b({USE_CASES})\b", text, re.I):
        d["use_case"] = m.group(1).lower()
    d["cap"] = G._cap(text)
    if d["cap"] is None and pending and pending.get("slot") == "budget":
        d["cap"] = _bare_amount(text)
    d["conditions"] = _conditions(text, pending)
    d["day"], d["day_error"] = _day(text, now)
    if pending and str(pending.get("slot", "")).startswith("model:"):
        cat = pending["slot"].split(":", 1)[1]
        i = _option_index(text, len(pending.get("options", [])))
        if i is not None:
            d["models"][cat] = pending["options"][i]
            d["unknown"].pop(cat, None)
            d["ambiguous"].pop(cat, None)
            if cat not in d["cats"]:
                d["cats"].append(cat)
    return d


# ---------------------------------------------------------------- the Claude reader (validated, never trusted)

SYSTEM = (
    "You read a shopper's message about buying PC parts and return ONLY a JSON object, no prose. Keys: "
    '"build" (true if they want a whole PC), '
    '"parts" (list of {"part": one of gpu|cpu|motherboard|memory|storage|cooler|psu|case, "model": the model text they '
    "typed, or null}), "
    '"use_case" (like "1440p" or null), "budget_usd" (a number they typed, or null), '
    '"conditions" (list from new|open-box|refurbished, or null), '
    '"deadline" (their words for the date, or null), "option" (1-3 if they are answering a numbered question, else null). '
    "Never invent a model, number or date the message does not contain. If a question was just asked (see "
    '"pending"), the message may be only its answer, for example "new" or "$1,300" or "2".'
)


def claude_llm(text: str, context: dict) -> dict | None:
    """One Claude call, bounded by TIMEOUT_S. None when there is no key or the call fails; the caller falls back."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or os.environ.get("BUYER_UNDERSTAND_LLM") == "0":
        return None
    import anthropic

    client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT_S, max_retries=0)
    resp = client.messages.create(model=MODEL, max_tokens=500, system=SYSTEM,
                                  messages=[{"role": "user", "content": json.dumps({"message": text, **context})}])
    raw = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    out = json.loads(raw)
    return out if isinstance(out, dict) else None


def llm_draft(raw: object, text: str, now: datetime, pending: dict | None) -> dict | None:
    """Turn the model's JSON into a draft, keeping only what the catalog and the owner's own words support."""
    if not isinstance(raw, dict):
        return None
    d = new_draft()
    d["texts"] = [text]
    d["build"] = raw.get("build") is True
    parts = raw.get("parts")
    for p in parts if isinstance(parts, list) else []:
        cat = p.get("part") if isinstance(p, dict) else None
        if cat not in catalog.CATEGORIES:
            continue
        if cat not in d["cats"]:
            d["cats"].append(cat)
        model = p.get("model")
        if isinstance(model, str) and model.strip():
            found = catalog.find_models(model, cat)
            if len(found) == 1:
                d["models"][cat] = found[0]
            elif len(found) > 1:
                d["ambiguous"][cat] = found
            elif cat in ("gpu", "psu"):
                d["unknown"][cat] = [" ".join(model.split())[:40]]  # asked about, never turned into a SKU
    uc = raw.get("use_case")
    if isinstance(uc, str) and re.fullmatch(USE_CASES, uc.strip(), re.I):
        d["use_case"] = uc.strip().lower()
    budget = raw.get("budget_usd")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and math.isfinite(budget) and budget > 0:
        typed = re.sub(r"[,\s]", "", text)
        if re.search(rf"(?<!\d){int(budget)}(?!\d)", typed) or re.search(rf"(?<!\d){budget:g}(?!\d)", typed):
            d["cap"] = float(budget)  # a number the owner really typed, not one the model made up
    conds = raw.get("conditions")
    if isinstance(conds, list):
        d["conditions"] = [c for c in CONDITIONS if c in conds] or None
    dl = raw.get("deadline")
    if isinstance(dl, str) and dl.strip():
        d["day"], d["day_error"] = _day(dl, now)
    opt = raw.get("option")
    if pending and str(pending.get("slot", "")).startswith("model:") and isinstance(opt, int) and not isinstance(opt, bool):
        if 1 <= opt <= len(pending.get("options", [])):
            cat = pending["slot"].split(":", 1)[1]
            d["models"][cat] = pending["options"][opt - 1]
            if cat not in d["cats"]:
                d["cats"].append(cat)
    return d


def _combine(rx: dict, ll: dict | None) -> dict:
    """Claude's reading, filled in by the regex reader wherever Claude had nothing. Typed numbers and dates win."""
    if ll is None:
        return rx
    d = new_draft()
    d["texts"] = rx["texts"]
    d["build"] = ll["build"] or rx["build"]
    d["cats"] = list(ll["cats"]) or list(rx["cats"])
    d["models"] = {**ll["models"], **rx["models"]}
    for key in ("unknown", "ambiguous"):
        d[key] = {**ll[key], **rx[key]}
    for cat in d["models"]:
        d["unknown"].pop(cat, None)
        d["ambiguous"].pop(cat, None)
    for cat in list(d["models"]) + list(d["unknown"]) + list(d["ambiguous"]):
        if cat not in d["cats"]:
            d["cats"].append(cat)
    d["use_case"] = rx["use_case"] or ll["use_case"]
    d["cap"] = rx["cap"] if rx["cap"] is not None else ll["cap"]
    d["conditions"] = rx["conditions"] or ll["conditions"]
    d["day"] = rx["day"] or ll["day"]
    d["day_error"] = None if d["day"] else (rx["day_error"] or ll["day_error"])
    return d


# ---------------------------------------------------------------- merging an answer into the unfinished goal

def _subject(d: dict) -> set:
    return set(d["cats"]) | (set(catalog.BUILD_PARTS) if d["build"] else set())


def merge(partial: dict | None, d: dict) -> dict:
    """Fold this message's draft into the sender's unfinished goal. A message about a different part starts fresh."""
    if partial is None:
        return d
    new, old = _subject(d), _subject(partial)
    if new and old and not (new <= old or old <= new):
        return d
    m = dict(partial, texts=partial["texts"] + d["texts"], pending=None)
    m["build"] = partial["build"] or d["build"]
    m["cats"] = list(partial["cats"]) + [c for c in d["cats"] if c not in partial["cats"]]
    m["models"] = {**partial["models"], **d["models"]}
    m["unknown"] = {c: v for c, v in {**partial["unknown"], **d["unknown"]}.items() if c not in d["models"]}
    m["ambiguous"] = {c: v for c, v in {**partial["ambiguous"], **d["ambiguous"]}.items() if c not in d["models"]}
    for cat in d["models"]:
        m["unknown"].pop(cat, None)
    m["use_case"] = d["use_case"] or partial["use_case"]
    m["cap"] = d["cap"] if d["cap"] is not None else partial["cap"]
    m["conditions"] = d["conditions"] or partial["conditions"]
    m["day"] = d["day"] or partial["day"]
    m["day_error"] = None if m["day"] else d["day_error"]
    m["notes"] = []
    return m


# ---------------------------------------------------------------- deciding what is still missing

def _money(x: float) -> str:
    return f"${x:,.0f}" if x == int(x) else f"${x:,.2f}"


def _so_far(d: dict, cats: list) -> str:
    bits = [catalog.label(d["models"][c]) if c in d["models"] else catalog.NAMES[c] for c in cats if c in d["models"]]
    if d["use_case"]:
        bits.append(d["use_case"])
    if d["cap"]:
        bits.append(f"under {_money(d['cap'])}")
    if d["conditions"]:
        bits.append("/".join(d["conditions"]))
    return ("So far: " + ", ".join(bits) + ". ") if bits else ""


def _ask_model(d: dict, cats: list, cat: str, opts: list, why: str) -> str:
    d["pending"] = {"slot": f"model:{cat}", "options": opts}
    lines = ", ".join(f"{i}) {catalog.label(s)}" + (f" (from {_money(catalog.floor()[s]['min_price'])})" if s in catalog.floor() else "")
                      for i, s in enumerate(opts, 1))
    return f"{_so_far(d, cats)}{why} Which {catalog.NAMES[cat]}? {lines}. Reply with the number or the name. Prices are from the sandbox sellers."


def _plan_cats(d: dict) -> list:
    cats = set(d["cats"]) | (set(catalog.BUILD_PARTS) if d["build"] else set())
    return [c for c in ORDER if c in cats]


def step(d: dict, buyer_id: str, now: datetime) -> tuple[str, object]:
    """('ask', text) | ('ready', None). Mutates d["pending"] and d["notes"]."""
    d["pending"], d["notes"] = None, []
    cats = _plan_cats(d)
    # 1. a model the catalog does not hold, or several at once: ask, never guess
    for cat, names in list(d["unknown"].items()) + [(c, None) for c in d["ambiguous"]]:
        opts = d["ambiguous"].get(cat) or catalog.options(cat, 3, d["cap"] if d["cap"] else None) or catalog.options(cat, 3)
        if names:
            why = f"I don't have {', '.join(n.upper() for n in names)} in my catalog and I won't guess a part number."
        else:
            why = "You named more than one."
        return "ask", _ask_model(d, cats, cat, opts, why)
    if not cats:
        return "ask", ("Which part are you after? I can hunt for a graphics card, a power supply, a case, "
                       "or shop a whole PC build. Add a budget and a date if you have them.")
    if d["cap"] is None:
        d["pending"] = {"slot": "budget", "options": []}
        return "ask", f"{_so_far(d, cats)}What is your maximum budget?"
    if not (d["cap"] > 0 and math.isfinite(d["cap"])):
        d["cap"], d["pending"] = None, {"slot": "budget", "options": []}
        return "ask", "The budget must be a positive amount. What is your maximum budget?"
    # 2. a model for every part that has no safe default
    told = {o["sku_spec"].split()[0] for o in G._owned(" ".join(d["texts"]), buyer_id, now)}
    for cat in cats:
        if cat in d["models"] or cat in ("psu", "case"):
            continue
        if cat == "gpu":
            rest = sum(catalog.cheapest(c) or 0 for c in cats if c in ("psu", "case") and c not in told)
            room = d["cap"] - rest
            fits = catalog.options("gpu", 3, room)
            if not fits:
                low = catalog.cheapest("gpu")
                d["cap"], d["pending"] = None, {"slot": "budget", "options": []}
                return "ask", (f"Under that budget I can't fit a graphics card: the cheapest one listed by today's sellers "
                               f"is {_money(low)}. What is your maximum budget?")
            if len(fits) == 1:
                d["models"]["gpu"] = fits[0]
                d["notes"].append(f"Only the {catalog.label(fits[0])} fits that budget on today's floor, so that is the card I will shop.")
                continue
            return "ask", _ask_model(d, cats, "gpu", fits, f"{'For the build, ' if d['build'] else ''}I won't pick a card for you.")
        return "ask", _ask_model(d, cats, cat, catalog.options(cat, 3), "I won't pick a part number for you.")
    if d["conditions"] is None:
        d["pending"] = {"slot": "condition", "options": []}
        return "ask", f"{_so_far(d, cats)}What condition do you want: new or open-box?"
    if d["day"] is None:
        d["pending"] = {"slot": "deadline", "options": []}
        err = f"{d['day_error']} " if d["day_error"] else ""
        d["day_error"] = None
        return "ask", f"{err}{_so_far(d, cats)}When is your deadline? Give a date, weekday, or tomorrow."
    return "ready", None


def _build_goal(d: dict, buyer_id: str, now: datetime) -> Outcome:
    text = " ".join(d["texts"])
    cats = _plan_cats(d)
    sku = {c: d["models"].get(c) or ("psu 750w" if c == "psu" else "case") for c in cats}
    conds = d["conditions"]
    items = [{"part": c, "sku_spec": sku[c], "condition": conds[0], "variant": "retail", "quantity": 1,
              **({"allowed_conditions": conds} if len(conds) > 1 else {})} for c in cats]
    goal = {"id": f"goal-{G.uuid.uuid4().hex[:8]}", "buyer_id": buyer_id,
            "type": "build_by_date" if d["build"] else "part_by_date", "items": items, "cap": d["cap"],
            "deadline": f"{d['day']}T23:59:00Z", "state": "ACTIVE", "reserved_amount": 0, "created_at": now.isoformat(),
            "notes": f"'{' '.join(t.strip() for t in d['texts'])}', {now.astimezone().strftime('%H:%M')}"}
    owned = G._owned(text, buyer_id, now)
    notes = list(d["notes"])
    unlisted = [catalog.NAMES[c] for c in cats if not catalog.is_listed(sku[c])]
    if unlisted:
        notes.append(f"No seller on today's floor lists {', '.join(unlisted)} yet, so expect no bids for that line.")
    if d["build"]:
        later = [catalog.NAMES[c] for c in ("cpu", "motherboard", "memory", "storage", "cooler") if c not in cats]
        notes.append(f"Shopping the {', '.join(catalog.NAMES[c] for c in cats)} now; no seller lists "
                     f"{', '.join(later)} yet.")
        try:
            import planner
            kept = {o["sku_spec"].split()[0]: o["attrs"] for o in owned}
            notes.append("Budget guide for the whole build: " + planner.plan(int(round(d["cap"] * 100)), kept)["steps"][0]["line"])
        except Exception:
            pass  # a guide line only; the goal does not depend on it
    return Outcome(goal=common.validate("Goal", goal), owned=owned, notes=notes)


# ---------------------------------------------------------------- the entry point

async def understand(text: str, buyer_id: str, sender: str, *, memory: ConversationMemory = MEMORY, llm=claude_llm,
                     now: datetime | None = None) -> Outcome:
    """Read one chat message. Returns a finished goal, or a reply (one question, or why nothing could be read)."""
    now = now or datetime.now(timezone.utc)
    partial = memory.get(sender)
    if CANCEL_RX.match(text):
        memory.clear(sender)
        return Outcome(reply="Okay, I dropped that goal. Nothing was ordered. Tell me what you want to buy when you are ready.")
    pending = partial.get("pending") if partial else None
    rx = regex_draft(text, now, pending)
    ll, source = None, "regex"
    if llm is not None:
        ctx = {"today": now.date().isoformat(), "pending": pending,
               "so_far": {k: partial[k] for k in ("cats", "models", "cap", "conditions", "day")} if partial else None}
        try:
            raw = await asyncio.wait_for(asyncio.to_thread(llm, text, ctx), TIMEOUT_S)
            ll = llm_draft(raw, text, now, pending)
        except Exception:  # timeout, no key, network, bad JSON: the regex reader answers instead
            ll = None
        source = "claude" if ll is not None and any(ll[k] for k in ("cats", "build", "use_case", "cap", "conditions", "day")) else "regex"
    try:
        draft = merge(partial, _combine(rx, ll))
        kind, reply = step(draft, buyer_id, now)
        if kind == "ask":
            memory.put(sender, draft)
            return Outcome(reply=reply, source=source)
        out = _build_goal(draft, buyer_id, now)  # validated against the Goal schema; a failure is a plain reply, not a crash
    except Exception:
        memory.clear(sender)
        return Outcome(reply="I could not read a goal from that. Tell me the part, a budget, new or open-box, and a date.")
    memory.clear(sender)
    out.source = source
    return out
