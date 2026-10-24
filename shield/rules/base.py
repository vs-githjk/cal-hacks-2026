"""Rule shape shared by every rule file. A rule is a module with one `RULE`; ids are stable strings."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from shield.text import Doc

BLOCK = "block"
QUARANTINE = "quarantine"
SEVERITY_ORDER = ("none", "low", "medium", "high", "critical")


@dataclass(frozen=True)
class Rule:
    id: str
    action: str  # block | quarantine
    severity: str  # low | medium | high | critical
    describe: str
    check: Callable[[Doc, Mapping], Iterable[tuple[int, int]]]  # returns raw-offset spans
    fold: bool = False  # also run on the folded views (leetspeak, spacing, accents undone); prose rules only


def finditer_spans(doc: Doc, patterns: Iterable["re.Pattern[str]"]):
    """Raw-offset spans of every match of any pattern in the normalised text."""
    for p in patterns:
        for m in p.finditer(doc.norm):
            if m.end() > m.start():
                yield doc.raw_span(m.start(), m.end())


def any_match(text: str, patterns: Iterable["re.Pattern[str]"]) -> bool:
    return any(p.search(text) for p in patterns)


def rx(pattern: str) -> "re.Pattern[str]":
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)
