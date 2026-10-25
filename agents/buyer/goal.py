"""Pure goal logic: buyer's words -> Goal + OwnedParts -> Need. Plain regex rules, no LLM in the money path."""
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import common

PARTS = {"gpu": r"gpu|graphics card|video card", "psu": r"psu|power supply", "case": r"case|mid-tower|full-tower|mini-tower|tower"}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
OWN_VERB = r"\b(?:own|have|got)\b"
# ponytail/SIM: part type -> seller sku until the real SpecCards land. Sellers match Need items by exact sku_spec.
SKUS = {"gpu": "rtx 4070 super 12gb", "psu": "psu 750w", "case": "case"}
SUPPORTED_GPUS = {"rtx 5070 ti": "rtx 5070 ti", "rtx 4070 super": "rtx 4070 super 12gb"}
OWNED: dict[str, list[dict]] = {}  # buyer_id -> OwnedParts; in memory, lost on restart


def _now(now):
    return now or datetime.now(timezone.utc)


def _deadline_day(text: str, now: datetime) -> date | None:
    t = text.lower()
    day = None
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t):
        day = datetime.fromisoformat(m.group(1)).date()
        if re.search(rf"\bbefore\s+{re.escape(m.group(1))}\b", t):
            day -= timedelta(days=1)
    elif "tomorrow" in t:
        day = (now + timedelta(days=1)).date()
    else:
        for i, name in enumerate(WEEKDAYS):
            if re.search(rf"\b{name}\b", t):
                day = (now + timedelta(days=(i - now.weekday()) % 7 or 7)).date()
                break
    if day is not None and day < now.astimezone(timezone.utc).date():
        raise ValueError("The requested deadline is in the past.")
    return day


def _deadline(text: str, now: datetime) -> str:
    day = _deadline_day(text, now)
    if day is None:
        raise ValueError("When do you need it? Give a date, weekday, or tomorrow.")
    return f"{day.isoformat()}T23:59:00Z"


_CAP_WORDS = r"(?:under|below|max|up to|less than|budget(?: of| is)?)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)"
_CAP_DOLLARS = r"\$\s*(\d[\d,]*(?:\.\d+)?)"


def _cap(text: str) -> float | None:
    m = re.search(_CAP_WORDS, text, re.I) or re.search(_CAP_DOLLARS, text)
    return float(m.group(1).replace(",", "")) if m else None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]


def _gpu_sku(text: str) -> str:
    branded = list(re.finditer(r"\b(?:RTX|RX|GTX)\s*\d{3,4}(?:\s*(?:Ti|SUPER|XT|XTX|GRE))?\b", text, re.I))
    candidates = [(m.group(0), m.span()) for m in branded]
    for alias in ("5070 Ti", "4070 Super"):
        alias_pattern = re.escape(alias).replace(r"\ ", r"\s*")
        for match in re.finditer(rf"\b{alias_pattern}\b", text, re.I):
            if not any(match.start() < end and start < match.end() for _, (start, end) in candidates):
                candidates.append((match.group(0), match.span()))
    if not candidates:
        unbranded = re.search(r"\b(?:(?:GPU|graphics card)\s*)?(\d{3,4}(?:\s*(?:Ti|SUPER|XT|XTX|GRE))?)\s*(?:GPU|graphics card)\b", text, re.I)
        if not unbranded:
            return SKUS["gpu"]  # legacy generic GPU goals remain the SIM control
        raise ValueError("Which GPU model? I can't resolve that request yet.")
    normalized = {" ".join(raw.lower().split()) for raw, _span in candidates}
    if len(normalized) > 1:
        raise ValueError("Name one GPU model so I know which one to find.")
    models = []
    for raw, _span in candidates:
        key = " ".join(raw.lower().split())
        if not re.match(r"^(?:rtx|rx|gtx)\b", key):
            key = "rtx " + key
        models.append((key, SUPPORTED_GPUS.get(key)))
    if any(sku is None for _, sku in models):
        raise ValueError("Which GPU model? I can't resolve that request yet.")
    resolved = {sku for _, sku in models}
    if len(resolved) != 1:
        raise ValueError("Name one GPU model so I know which one to find.")
    return next(iter(resolved))


def _allowed_conditions(text: str) -> list[str] | None:
    new = bool(re.search(r"\bnew\b", text, re.I))
    open_box = bool(re.search(r"\bopen[- ]box\b", text, re.I))
    if new and open_box:
        return ["new", "open-box"]
    if open_box:
        return ["open-box"]
    if new:
        return ["new"]
    return None


def _clarification_question(text: str, now: datetime) -> str | None:
    cap = _cap(text)
    if cap is None:
        return "What is your maximum budget?"
    if not (cap > 0 and math.isfinite(cap)):
        raise ValueError("The budget must be a positive finite amount.")
    if _allowed_conditions(text) is None:
        return "What condition do you want: new or open-box?"
    if _deadline_day(text, now) is None:
        return "When is your deadline? Give a date, weekday, or tomorrow."
    return None


def clarification_question(text: str) -> str | None:
    """Return the next required goal clarification in stable order, or None when complete."""
    return _clarification_question(text, _now(None))


def _owned(text: str, buyer_id: str, now: datetime) -> list[dict]:
    out = []
    for s in _sentences(text):
        if not re.search(OWN_VERB, s, re.I):
            continue
        note = f"'{s.rstrip('.')}', {now.astimezone().strftime('%H:%M')}"

        def part(sku, name, attrs):
            out.append(common.validate("OwnedPart", {
                "id": f"owned-{uuid.uuid4().hex[:8]}", "buyer_id": buyer_id, "sku_spec": sku, "item_name": name,
                "condition": "unknown", "acquired_on": "", "source": "told_by_user", "attrs": attrs, "notes": note}))

        if m := re.search(r"(\d{3,4})\s*-?\s*w(?:atts?)?\b[^.;,]*?\b(?:psu|power supply)", s, re.I):
            part(f"psu {m.group(1)}w", m.group(0), {"wattage": int(m.group(1))})
        elif m := re.search(rf"\b(?:{PARTS['psu']})\b", s, re.I):
            part("psu", m.group(0), {})
        if m := re.search(rf"\b(?:{PARTS['case']})\b", s, re.I):
            attrs = {}
            if c := re.search(r"(\d{2,3})\s*mm\s*(?:of\s+)?gpu clearance|gpu clearance (?:of\s+)?(\d{2,3})\s*mm", s, re.I):
                attrs["max_gpu_length_mm"] = int(c.group(1) or c.group(2))
            part(f"case {m.group(0).lower()}", m.group(0), attrs)
    return out


def _cats(text: str) -> list[str]:
    """The part kinds a goal text names (a build means GPU, PSU and case)."""
    t = text.lower()
    cats = ["gpu", "psu", "case"] if re.search(r"\bbuild\b", t) else [c for c, rx in PARTS.items() if re.search(rf"\b(?:{rx})\b", t)]
    if re.search(r"\b(?:RTX|RX|GTX)\s*\d{3,4}\b|\b\d{3,4}\s*(?:GPU|graphics card)\b", text, re.I) and "gpu" not in cats:
        cats.append("gpu")
    return cats


def parse_goal(text: str, buyer_id: str, now: datetime | None = None) -> tuple[dict, list[dict]]:
    """Raise ValueError until the required budget, condition, deadline and item are explicit."""
    now = _now(now)
    question = _clarification_question(text, now)
    if question:
        raise ValueError(question)
    t = text.lower()
    cap = _cap(text)
    if cap is None:
        raise ValueError("Tell me a budget, e.g. 'under $800'.")
    build = re.search(r"\bbuild\b", t)
    cats = _cats(text)
    if not cats:
        raise ValueError("Which part? I can hunt for a GPU, PSU or case (or a whole build).")
    sku = dict(SKUS, gpu=_gpu_sku(text), psu="psu 850w" if re.search(r"\b850\s*-?\s*w", t) else SKUS["psu"])
    conditions = _allowed_conditions(text)
    items = [{"part": c, "sku_spec": sku[c], "condition": conditions[0], "variant": "retail", "quantity": 1,
              **({"allowed_conditions": conditions} if len(conditions) > 1 else {})} for c in cats]
    has_date = re.search(r"\b(by|before|tomorrow|\d{4}-\d{2}-\d{2})\b", t) or any(d in t for d in WEEKDAYS)
    goal = {"id": f"goal-{uuid.uuid4().hex[:8]}", "buyer_id": buyer_id,
            "type": "build_by_date" if build else "part_by_date" if has_date else "budget_cap",
            "items": items, "cap": cap, "deadline": _deadline(text, now), "state": "ACTIVE",
            "reserved_amount": 0, "created_at": now.isoformat(),
            "notes": f"'{text.strip()}', {now.astimezone().strftime('%H:%M')}"}
    return common.validate("Goal", goal), _owned(text, buyer_id, now)


# ---- #449 RT-6: a goal said over several chat messages ----
# parse_goal reads one message alone, so "find me an RTX 5070 Ti under $1300" got "What condition?" and the answer "new" got
# "What is your maximum budget?". The chat keeps what a sender has said so far and reads it together with their next message.
DRAFT_TTL_S = 600        # a half-said goal is kept this long after that sender's last message
DRAFT_MAX = 64           # senders kept at once; the oldest goes first
DRAFT_MAX_CHARS = 1000   # a longer text is not kept
DRAFTS: dict[str, tuple[datetime, str]] = {}  # sender -> (when it was kept, the goal so far); in memory, lost on restart
_DATE_WORDS = rf"\b\d{{4}}-\d{{2}}-\d{{2}}\b|\btomorrow\b|\b(?:{'|'.join(WEEKDAYS)})\b"


def _is_draft(text: str, now: datetime) -> bool:
    """A text worth keeping: it names a part and only needs more answers (budget, condition or deadline), not small talk."""
    try:
        return bool(_cats(text)) and _clarification_question(text, now) is not None
    except ValueError:
        return False


def _merge_draft(draft: str, reply: str, now: datetime) -> str:
    """The draft and the reply as one text. What the reply says again (budget, condition, deadline) replaces the draft's own
    answer, so the latest reply wins."""
    if _cap(reply) is not None:
        draft = re.sub(_CAP_DOLLARS, " ", re.sub(_CAP_WORDS, " ", draft, flags=re.I))
    if _allowed_conditions(reply) is not None:
        draft = re.sub(r"\bnew\b|\bopen[- ]box\b", " ", draft, flags=re.I)
    try:
        dated = _deadline_day(reply, now) is not None
    except ValueError:      # a past date in the reply is still the reply's answer; the parse reports it
        dated = True
    if dated:
        draft = re.sub(_DATE_WORDS, " ", draft, flags=re.I)
    draft = " ".join(draft.split()).rstrip(" ,")
    return f"{draft}{' ' if draft.endswith(('.', '!', '?', ';')) else ', '}{reply.strip()}"


def forget_draft(buyer_id: str, drafts: dict | None = None) -> bool:
    """Drop a sender's half-said goal (CANCEL). True when there was one."""
    return (DRAFTS if drafts is None else drafts).pop(buyer_id, None) is not None


def parse_goal_draft(text: str, buyer_id: str, now: datetime | None = None, drafts: dict | None = None) -> tuple[dict, list[dict]]:
    """parse_goal, plus the sender's half-said goal. A message that is a whole goal on its own is read alone. Otherwise, if this
    sender said part of a goal in the last DRAFT_TTL_S seconds, the two are read together. A text that names a part and still
    needs an answer is kept for the sender's next message; a parsed goal clears it. Another sender's draft is never used."""
    now = _now(now)
    store = DRAFTS if drafts is None else drafts
    for gone in [k for k, (at, _) in store.items() if (now - at).total_seconds() > DRAFT_TTL_S]:
        del store[gone]
    draft = store.pop(buyer_id, None)

    def keep(kept: str):
        if len(kept) <= DRAFT_MAX_CHARS and _is_draft(kept, now):
            store[buyer_id] = (now, kept)
            while len(store) > DRAFT_MAX:
                del store[min(store, key=lambda k: store[k][0])]

    try:
        return parse_goal(text, buyer_id, now)
    except ValueError:
        if draft is None:
            keep(text)
            raise
    merged = _merge_draft(draft[1], text, now)
    try:
        return parse_goal(merged, buyer_id, now)
    except ValueError:
        keep(merged)
        raise


def remember(buyer_id: str, parts: list[dict]) -> list[dict]:
    """Add newly told parts to the buyer's store; a newer entry of the same kind replaces the older one."""
    store = OWNED.setdefault(buyer_id, [])
    for p in parts:
        kind = p["sku_spec"].split()[0]
        store[:] = [o for o in store if o["sku_spec"].split()[0] != kind] + [p]
    return store


def _rebuy(goal: dict, kind: str) -> bool:
    return bool(re.search(rf"\b(?:upgrade|replace)\w*\b[^.;]*\b(?:{PARTS[kind]})\b", goal.get("notes", ""), re.I))


def apply_owned(goal: dict, owned: list[dict]) -> dict:
    """Mark lines the buyer already owns with skipped_owned_part_id, unless they asked to upgrade/replace it."""
    for item in goal["items"]:
        kind = item["part"]
        hit = next((o for o in owned if o["sku_spec"].split()[0] == kind), None)
        if hit and not _rebuy(goal, kind):
            item["skipped_owned_part_id"] = hit["id"]
    return common.validate("Goal", goal)


def need_from_goal(goal: dict, auction_window_s: int = 12) -> dict:
    items = [{"sku_spec": i["sku_spec"], "condition": i.get("condition", "new"), "variant": i.get("variant", "retail"),
              "quantity": i["quantity"], "unit": "each", "grade": i.get("condition", "new"),
              "pack_size": i.get("variant", "retail"), **({"allowed_conditions": i["allowed_conditions"]} if i.get("allowed_conditions") else {})}
             for i in goal["items"] if not i.get("skipped_owned_part_id")]
    return common.validate("Need", {
        "id": f"need-{uuid.uuid4().hex[:8]}", "buyer_id": goal["buyer_id"], "items": items,
        "delivery_window": f"by {goal['deadline']}", "spend_limit": goal["cap"], "consent": True,
        "auction_window_s": auction_window_s, "source": "live"})


def skip_lines(goal: dict, owned: list[dict]) -> list[str]:
    by_id = {o["id"]: o for o in owned}
    label = {"gpu": "GPU", "psu": "PSU", "case": "case"}
    return [f"Skipped {label[i['part']]}: you already own it (your note: {by_id[i['skipped_owned_part_id']]['notes']})"
            for i in goal["items"] if i.get("skipped_owned_part_id") in by_id]


def owned_attrs(owned: list[dict]) -> dict:
    """What the advocate gets for fit checks: {"psu": {"wattage": 750}, "case": {...}}."""
    return {o["sku_spec"].split()[0]: o["attrs"] for o in owned}
