"""shield.price.contradiction: a "was $X" price that the price history never showed.

Takes `context["price_history"]` (numbers or {"price": n}) as input and never calls the network. With no
history there is nothing to compare, so the rule stays silent. The claim is flagged when it is more than
5 percent above the highest price in the history.
"""
import re

from shield.rules.base import QUARANTINE, Rule, rx

TOLERANCE = 1.05
_NUM = r"\$\s*(?P<n>\d[\d,]*(?:\.\d{1,2})?)"
PATTERNS = [
    rx(r"\b(?:was|originally|formerly|previously|regular\s+price|compare\s+at|reg\.?)\s*:?\s*" + _NUM),
    rx(r"<(?:s|del|strike)\b[^>]*>\s*" + _NUM),
    rx(r"[\"']was_price[\"']\s*:\s*[\"']?(?P<n>\d[\d,]*(?:\.\d{1,2})?)"),
]


def _history(ctx) -> list[float]:
    out = []
    for h in (ctx or {}).get("price_history") or []:
        v = h.get("price") if isinstance(h, dict) else h
        out.append(float(v))
    return out


def check(doc, ctx):
    hist = _history(ctx)
    if not hist:
        return
    ceiling = max(hist) * TOLERANCE
    for p in PATTERNS:
        for m in p.finditer(doc.norm):
            if float(m.group("n").replace(",", "")) > ceiling:
                yield doc.raw_span(m.start(), m.end())


RULE = Rule("shield.price.contradiction", QUARANTINE, "medium",
            "a was-price claim that the price history does not support", check)
