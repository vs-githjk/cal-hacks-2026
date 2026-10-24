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
    # fillers and marks that render as nothing or a blank: Hangul fillers, braille blank, combining grapheme joiner,
    # variation selector 16, Mongolian FVS1, Khmer inherent vowel, tag space, Arabic letter mark. Dropped, so an in-word
    # one glues the word back for every rule ("instruc<U+2800>tions"); secret_ask reads them once more as word gaps.
    "ㅤﾠ⠀ᅟ឵͏️᠋󠀠؜"
)

# Small, deliberate table: the look-alikes attackers actually use to dodge keyword filters.
_CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
    "һ": "h", "ԁ": "d", "ԛ": "q", "ѡ": "w", "к": "k", "м": "m", "т": "t", "н": "h", "в": "b",
    "ο": "o", "α": "a", "ν": "v", "ι": "i", "ρ": "p", "τ": "t", "υ": "u", "κ": "k", "ε": "e",
    "ı": "i", "ѵ": "v", "ӏ": "l", "ɑ": "a", "ᴏ": "o", "ɡ": "g", "ο": "o", "ӓ": "a", "ё": "e", "ї": "i",
}

_TOKEN = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z]+);|.", re.DOTALL)


@dataclass
class Doc:
    raw: str
    norm: str
    starts: list[int]
    ends: list[int]
    invisible: list[int] = field(default_factory=list)
    cache: dict = field(default_factory=dict, repr=False)  # per-message memo for rules that share work

    def views(self) -> list["Doc"]:
        """Extra Docs of the same message with leetspeak, letter spacing and accents undone (see fold_views).
        Rules that read prose also run on these; spans still map back to the caller's raw text."""
        if "views" not in self.cache:
            self.cache["views"] = fold_views(self)
        return self.cache["views"]

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


# ---------------------------------------------------------------------------------------------------------
# Folded views: undo the tricks that hide words from a keyword filter. Spans are kept by an index map.

_LEET = {"0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
_RUN = re.compile(r"(?<![a-z0-9@$])[a-z0-9@$](?:[ ._*\-][a-z0-9@$]){3,}(?![a-z0-9@$])")
_TOKEN_CHARS = re.compile(r"[a-z0-9@$]+")
_MAX_FOLD_CHARS = 20000

# Words used to re-space a run of single letters typed with single spaces ("s k i p t h e ..."). Greedy
# dynamic programming over this list; when the run does not split cleanly it is just joined.
_SEG_VOCAB = frozenset("""a an and any all are as at be buyer by call card charge check checks confirm deal do
for forget from go ahead disregard funds human if in instructions instruction ignore is it me my need new no not
now of off old on one or order owner pay payment please previous prior proceed release rules same send ship
sign skip step system the then this to transfer user verification verified approve approved approval advocate
agent assistant account bank wire money we with without you your already urgent immediately note instead
override bypass review""".split())


def _segment(letters: str) -> list[str] | None:
    n = len(letters)
    best: list[list[str] | None] = [None] * (n + 1)
    best[0] = []
    for i in range(1, n + 1):
        for j in range(max(0, i - 14), i):
            if best[j] is not None and letters[j:i] in _SEG_VOCAB:
                cand = best[j] + [letters[j:i]]
                if best[i] is None or len(cand) < len(best[i]):
                    best[i] = cand
    return best[n]


def _despace(chars: list[str], idx: list[int]) -> tuple[list[str], list[int]]:
    s = "".join(chars)
    out_c: list[str] = []
    out_i: list[int] = []
    pos = 0
    for m in _RUN.finditer(s):
        if sum(c.isalpha() for c in m.group(0)) < 3:
            continue
        out_c += chars[pos:m.start()]
        out_i += idx[pos:m.start()]
        run = m.group(0)
        seps = {c for c in run[1::2]}
        letters_at = list(range(m.start(), m.end(), 2))
        if seps == {" "}:
            word = "".join(run[0::2])
            seg = _segment(word) if len(word) >= 8 else None
            if seg:  # re-space at the segmentation boundaries
                k = 0
                for w in seg:
                    for _ in w:
                        out_c.append(s[letters_at[k]])
                        out_i.append(idx[letters_at[k]])
                        k += 1
                    out_c.append(" ")
                    out_i.append(idx[letters_at[k - 1]])
                out_c.pop(), out_i.pop()
            else:
                out_c += [s[p] for p in letters_at]
                out_i += [idx[p] for p in letters_at]
        else:  # dots, dashes, underscores: a space between them is a word break
            for k, p in enumerate(letters_at):
                out_c.append(s[p])
                out_i.append(idx[p])
                if k + 1 < len(letters_at) and run[(p - m.start()) + 1] == " ":
                    out_c.append(" ")
                    out_i.append(idx[p])
        pos = m.end()
    out_c += chars[pos:]
    out_i += idx[pos:]
    return out_c, out_i


def _leet(chars: list[str], one: str) -> list[str]:
    s = "".join(chars)
    out = list(chars)
    for m in _TOKEN_CHARS.finditer(s):
        tok = m.group(0)
        if sum(c.isalpha() for c in tok) < 2 or not any(c in _LEET or c == "1" for c in tok):
            continue
        for k, c in enumerate(tok):
            out[m.start() + k] = one if c == "1" else _LEET.get(c, c)
    return out


def fold_views(doc: "Doc") -> list["Doc"]:
    """One or two folded copies of doc.norm: accents dropped, single-letter runs joined, leetspeak decoded
    (a "1" read as i in one copy and as l in the other). Empty when folding changes nothing."""
    norm = doc.norm
    if not norm or len(norm) > _MAX_FOLD_CHARS:
        return []
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(norm):
        for c in unicodedata.normalize("NFD", ch):
            if not unicodedata.combining(c):
                chars.append(c)
                idx.append(i)
    chars, idx = _despace(chars, idx)
    # collapse runs of blanks so phrases split by padding still match
    c2: list[str] = []
    i2: list[int] = []
    for c, i in zip(chars, idx):
        if c in " \t" and c2 and c2[-1] == " ":
            continue
        c2.append(" " if c == "\t" else c)
        i2.append(i)
    variants = [_leet(c2, "i")]
    if "1" in c2:
        variants.append(_leet(c2, "l"))
    views = []
    seen = {norm}
    for v in variants:
        text = "".join(v)
        if text in seen:
            continue
        seen.add(text)
        views.append(Doc(raw=doc.raw, norm=text, starts=[doc.starts[i] for i in i2],
                         ends=[doc.ends[i] for i in i2], invisible=doc.invisible))
    return views
