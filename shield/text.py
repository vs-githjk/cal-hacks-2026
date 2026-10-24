"""Text normalisation with an index map, so a rule can match on clean text and report spans in the raw message.

Normalising removes zero-width and bidi control characters, decodes HTML entities, applies NFKC, folds the
common Cyrillic and Greek look-alike letters to Latin, and lowercases. Every rule runs on `Doc.norm`;
`Doc.raw_span` maps a match back to offsets in the message the caller sent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

INVISIBLE = frozenset(
    "​‌‍‎‏⁠⁡⁢⁣⁤﻿­᠎"
    "‪‫‬‭‮⁦⁧⁨⁩"
)

# Small, deliberate table: the look-alikes attackers actually use to dodge keyword filters.
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
    "һ": "h", "ԁ": "d", "ԛ": "q", "ѡ": "w", "к": "k", "м": "m", "т": "t", "н": "h", "в": "b",
    "ο": "o", "α": "a", "ν": "v", "ι": "i", "ρ": "p", "τ": "t", "υ": "u", "κ": "k", "ε": "e",
}

_TOKEN = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z]+);|.", re.DOTALL)


@dataclass
class Doc:
    raw: str
    norm: str
    starts: list[int]
    ends: list[int]
    invisible: list[int] = field(default_factory=list)

    def raw_span(self, ns: int, ne: int) -> tuple[int, int]:
        """Map a half-open span of `norm` to a half-open span of `raw`."""
        ns = max(0, min(ns, len(self.norm) - 1))
        ne = max(ns + 1, min(ne, len(self.norm)))
        return self.starts[ns], self.ends[ne - 1]


def make_doc(raw: str) -> Doc:
    import html

    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    invisible: list[int] = []
    for m in _TOKEN.finditer(raw):
        tok = m.group(0)
        if len(tok) == 1 and tok in INVISIBLE:
            invisible.append(m.start())
            continue
        piece = html.unescape(tok) if len(tok) > 1 else tok
        for ch in unicodedata.normalize("NFKC", piece):
            if ch in INVISIBLE:
                continue
            for c in ch.lower():
                out.append(_CONFUSABLES.get(c, c))
                starts.append(m.start())
                ends.append(m.end())
    return Doc(raw=raw, norm="".join(out), starts=starts, ends=ends, invisible=invisible)
