"""One plain sentence per card, from code. The decision (recommendation, rule id, source link) is already on the card;
this only says it in words. A model may reword the sentence later (phrasing.phrase) but never touches the card.
"""
from __future__ import annotations

import re

INFO_KINDS = {"note"}
LEADS = {"veto": "Veto", "caution": "Caution", "buy": "Approved"}


def lead_sentence(text: str) -> str:
    """The first sentence of a warning, ending in a full stop. Warning text is built from code templates."""
    text = " ".join(str(text or "").split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    return first if first.endswith((".", "!", "?")) else (first + ".") if first else ""


def sentence(card: dict) -> str:
    """The one-sentence explanation for a card: its verdict word, then the fact that decided it."""
    rec = card.get("recommendation")
    warnings = card.get("warnings") or []
    lead = LEADS.get(rec, "Caution")
    if rec == "buy":
        notes = [w for w in warnings if w.get("kind") in INFO_KINDS]
        if notes:
            return f"Approved with a note: {lead_sentence(notes[0].get('text'))}"
        return "Approved: the price, fit, recall and condition checks found no problem."
    rid = card.get("rule_id")
    decisive = next((w for w in warnings if w.get("rule_id") == rid and w.get("kind") not in INFO_KINDS), None)
    decisive = decisive or next((w for w in warnings if w.get("kind") not in INFO_KINDS), None)
    fact = lead_sentence(decisive.get("text")) if decisive else str(card.get("reason") or "").rstrip(".") + "."
    return f"{lead}: {fact}"


def attach(card: dict) -> dict:
    """Add `explanation` and its source link to a card (the link is the card's own cited source)."""
    card["explanation"] = sentence(card)
    card["explanation_source_url"] = card.get("source_url", "")
    return card
