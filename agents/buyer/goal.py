"""Pure goal logic: buyer's words -> Goal + OwnedParts -> Need. Plain regex rules, no LLM in the money path."""
import re
import uuid
from datetime import datetime, timedelta, timezone

import common

PARTS = {"gpu": r"gpu|graphics card|video card", "psu": r"psu|power supply", "case": r"case|mid-tower|full-tower|mini-tower|tower"}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
OWN_VERB = r"\b(?:own|have|got)\b"
# ponytail/SIM: part type -> seller sku until the real SpecCards land. Sellers match Need items by exact sku_spec.
SKUS = {"gpu": "rtx 4070 super 12gb", "psu": "psu 750w", "case": "case"}
OWNED: dict[str, list[dict]] = {}  # buyer_id -> OwnedParts; in memory, lost on restart


def _now(now):
    return now or datetime.now(timezone.utc)


def _deadline(text: str, now: datetime) -> str:
    t = text.lower()
    day = None
    if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t):
        day = datetime.fromisoformat(m.group(1)).date()
    elif "tomorrow" in t:
        day = (now + timedelta(days=1)).date()
    else:
        for i, name in enumerate(WEEKDAYS):
            if re.search(rf"\b{name}\b", t):
                day = (now + timedelta(days=(i - now.weekday()) % 7 or 7)).date()
                break
    day = day or (now + timedelta(days=7)).date()
    return f"{day.isoformat()}T23:59:00Z"


def _cap(text: str) -> float | None:
    m = (re.search(r"(?:under|below|max|up to|less than|budget(?: of| is)?)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)", text, re.I)
         or re.search(r"\$\s*(\d[\d,]*(?:\.\d+)?)", text))
    return float(m.group(1).replace(",", "")) if m else None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]


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


def parse_goal(text: str, buyer_id: str, now: datetime | None = None) -> tuple[dict, list[dict]]:
    """Raise ValueError when the goal has no budget or names no part."""
    now = _now(now)
    t = text.lower()
    cap = _cap(text)
    if cap is None:
        raise ValueError("Tell me a budget, e.g. 'under $800'.")
    build = re.search(r"\bbuild\b", t)
    cats = ["gpu", "psu", "case"] if build else [c for c, rx in PARTS.items() if re.search(rf"\b(?:{rx})\b", t)]
    if not cats:
        raise ValueError("Which part? I can hunt for a GPU, PSU or case (or a whole build).")
    sku = dict(SKUS, psu="psu 850w" if re.search(r"\b850\s*-?\s*w", t) else SKUS["psu"])
    items = [{"part": c, "sku_spec": sku[c], "condition": "new", "variant": "retail", "quantity": 1} for c in cats]
    has_date = re.search(r"\b(by|before|tomorrow|\d{4}-\d{2}-\d{2})\b", t) or any(d in t for d in WEEKDAYS)
    goal = {"id": f"goal-{uuid.uuid4().hex[:8]}", "buyer_id": buyer_id,
            "type": "build_by_date" if build else "part_by_date" if has_date else "budget_cap",
            "items": items, "cap": cap, "deadline": _deadline(text, now), "state": "ACTIVE",
            "reserved_amount": 0, "created_at": now.isoformat(),
            "notes": f"'{text.strip()}', {now.astimezone().strftime('%H:%M')}"}
    return common.validate("Goal", goal), _owned(text, buyer_id, now)


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
              "pack_size": i.get("variant", "retail")}
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
