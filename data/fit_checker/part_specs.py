"""Maker specs for the exact CPU, board, memory, storage and cooler models we hold real listings for (Lane C, #342).

find(category, model_number=None, title=None) -> row or None
maker(category, name) -> {check_build attr: (value, "maker page URL (checked DATE)")}

part_specs.json holds one row per EXACT model, filled by hand from the maker's own page: brand, model_number, a strict
`match` regex over the listing title (and an optional `exclude`, so a 9700X never matches a 9700X3D), the specs the fit rules
read, `source` (the maker page) and `checked` (date). A model with no row is unknown: it gets no specs and never bids as
MIRROR. Nothing is guessed from a sibling model, a chipset or seller text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "part_specs.json"
CATEGORIES = ("cpu", "motherboard", "memory", "storage", "cooler")
# row field -> the attr name check_build / check_fit reads for that category
ATTRS = {
    "cpu": {"socket": "socket", "tdp_w": "tdp_w", "arch": "microarchitecture"},
    "motherboard": {"socket": "socket", "memory_type": "memory_type", "memory_form": "memory_form", "memory_slots": "memory_slots",
                    "memory_max_speed_mhz": "memory_max_speed_mhz", "form_factor": "form_factor", "m2_slots": "m2_slots"},
    "memory": {"memory_type": "type", "speed_mhz": "speed_mhz", "modules": "modules", "form": "form"},
    "storage": {"interface": "interface", "form": "form"},
    "cooler": {"height_mm": "height_mm", "sockets": "sockets"},
}
# a bundle, a laptop or a prebuilt is never the bare part, even when its title names the model
NOT_A_PART = re.compile(r"\b(combo|bundle|laptop|notebook|prebuilt|pre-built|gaming pc|gaming desktop|desktop pc|desktop computer|mini pc|all-in-one)\b", re.I)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def rows(category: str) -> list[dict]:
    try:
        data = json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get(category) if isinstance(data, dict) else None
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


def find(category: str, model_number=None, title=None) -> dict | None:
    """The row for this exact model, else None. The maker's model number first (case and punctuation ignored), then the
    row's strict title rule. No fuzzy matching, no substring of a shorter name."""
    if category not in CATEGORIES:
        return None
    have = _norm(model_number)
    title = str(title or "")
    for r in rows(category):
        known = {_norm(r.get("model_number"))} | {_norm(m) for m in r.get("also_model_numbers") or []}
        known.discard("")
        if have and have in known and not NOT_A_PART.search(title):
            return r
    for r in rows(category):
        pat = r.get("match")
        if not title or not pat or NOT_A_PART.search(title):
            continue
        if re.search(pat, title, re.I) and not (r.get("exclude") and re.search(r["exclude"], title, re.I)):
            return r
    return None


def specs(category: str, row: dict | None) -> dict:
    """{check attr: (value, source)} for a row, every figure citing the maker page and the date it was checked."""
    if not row:
        return {}
    cite = f"{row.get('source')} (maker page, checked {row.get('checked')})"
    return {attr: (row[f], cite) for f, attr in ATTRS.get(category, {}).items() if row.get(f) not in (None, "", [])}


def maker(category: str, name: str) -> dict:
    return specs(category, find(category, None, name))
