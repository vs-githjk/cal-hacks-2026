"""shield.encoded.payload: oversized messages, base64 or hex blobs, escape runs and look-alike letters."""
import binascii
import re
import unicodedata

from shield.rules.base import QUARANTINE, Rule, rx

MAX_CHARS = 20000
_B64 = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])")
_HEX = re.compile(r"\b[0-9a-fA-F]{80,}\b")
_ESC = rx(r"(?:\\u[0-9a-f]{4}|\\x[0-9a-f]{2}){6,}|(?:%[0-9a-f]{2}){12,}")
_WORD = re.compile(r"\w+")


def _is_b64_blob(s: str) -> bool:
    if not (re.search(r"[A-Z]", s) and re.search(r"[a-z]", s)):
        return False
    t = s.replace("-", "+").replace("_", "/").rstrip("=")
    try:
        binascii.a2b_base64(t + "=" * (-len(t) % 4))
    except (binascii.Error, ValueError):
        return False
    return True


def _script(ch: str) -> str:
    o = ord(ch)
    if 0x0400 <= o <= 0x04FF:
        return "cyr"
    if 0x0370 <= o <= 0x03FF:
        return "gre"
    return "lat" if ch.isascii() and ch.isalpha() else ""


def check(doc, ctx):
    raw = doc.raw
    if len(raw) > MAX_CHARS:
        yield 0, min(80, len(raw))
        return
    for m in _B64.finditer(raw):
        if _is_b64_blob(m.group(0)):
            yield m.start(), m.end()
    for p in (_HEX, _ESC):
        for m in p.finditer(raw):
            yield m.start(), m.end()
    for m in _WORD.finditer(raw):
        scripts = {s for s in map(_script, m.group(0)) if s}
        if "lat" in scripts and scripts & {"cyr", "gre"}:
            yield m.start(), m.end()
    wide = [i for i, ch in enumerate(raw) if ord(ch) > 0xFF and ch.isalpha()
            and unicodedata.normalize("NFKC", ch).isascii()]
    if len(wide) >= 4:
        yield wide[0], wide[-1] + 1


RULE = Rule("shield.encoded.payload", QUARANTINE, "medium",
            "oversized or encoded payload, or look-alike letters hiding words", check)
