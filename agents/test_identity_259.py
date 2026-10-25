"""#259: agent display names under 20 characters, five-section READMEs, one avatar per agent (read from the files,
so no agent is constructed)."""
import re
import struct
import zlib
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parent
SECTIONS = ("## Summary", "## Features", "## Usage examples", "## Use cases", "## Limitations")
# The live roster (#398: four sellers, four jobs) plus the two retired sellers whose files still exist.
AVATAR_ROLES = {"buyer", "advocate", "shield", "caller", "pulse", "seller_1", "seller_3", "seller_5", "seller_6"}
RETIRED_ROLES = {"seller_2", "seller_4"}
CORAL = (229, 72, 77)   # --coral-mark #e5484d, the Caller's accent (docs/design-system/tokens.css)


@pytest.mark.parametrize("path,pattern", [
    ("advocate/advocate_agent.py", r'name="([^"]+)"'), ("shield_client.py", r"name='([^']+)'"),
    ("caller/caller_agent.py", r'NAME = "([^"]+)"'), ("buyer/buyer_agent.py", r'name="([^"]+)"'),
])
def test_display_names_match_agentverse_and_the_short_ones_are_under_20_characters(path, pattern):
    name = re.search(pattern, (AGENTS / path).read_text()).group(1)
    long_names = {"Fish Market Quality Advocate", "Fish Market Smell Test"}  # renamed on Agentverse (#383)
    assert name in long_names or len(name) < 20, name


@pytest.mark.parametrize("readme", ["advocate/AGENTVERSE.md", "SHIELD_AGENTVERSE.md", "caller/AGENTVERSE.md",
                                    "buyer/AGENTVERSE.md", *[f"sellers/AGENTVERSE-seller_{i}.md" for i in range(1, 7)]])
def test_every_readme_has_the_five_sections(readme):
    text = (AGENTS / readme).read_text()
    assert all(s in text for s in SECTIONS), [s for s in SECTIONS if s not in text]
    assert "—" not in text and "–" not in text


def decode_png(data: bytes) -> tuple[int, int, int, bytes]:
    """(width, height, bytes per pixel, unfiltered pixel rows) for an 8-bit non-interlaced RGB or RGBA PNG.
    Reads every IDAT chunk (encoders split the stream) and undoes all five scanline filters."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8: pos + 8 + length]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + length
    width, height, depth, color, _, _, interlace = ihdr
    assert depth == 8 and color in (2, 6) and interlace == 0, ihdr
    bpp = 3 if color == 2 else 4
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    prev = bytearray(stride)
    rows = bytearray()
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1: start + 1 + stride])
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif kind == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 255
        rows += line
        prev = line
    return width, height, bpp, bytes(rows)


def count_color(png: bytes, rgb: tuple[int, int, int]) -> int:
    width, height, bpp, rows = decode_png(png)
    needle = bytes(rgb)
    return sum(1 for i in range(0, len(rows), bpp) if rows[i:i + 3] == needle)


def test_one_png_avatar_per_agent_and_the_caller_is_the_one_coral_tile():
    coral = {}
    for n in AVATAR_ROLES | RETIRED_ROLES:
        data = (AGENTS / "avatars" / f"{n}.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", n
        coral[n] = count_color(data, CORAL)
    # the live avatars are the 512 tiles rendered from agents/avatars/src/<role>.svg
    for n in AVATAR_ROLES:
        width, height, _, _ = decode_png((AGENTS / "avatars" / f"{n}.png").read_bytes())
        assert (width, height) == (512, 512), (n, width, height)
    # the Caller (the one approval phone call) is the one coral avatar; every other tile has at most a few coral pixels
    assert coral["caller"] > 5000, coral["caller"]
    others = {n: c for n, c in coral.items() if n != "caller" and c > 100}
    assert not others, others


@pytest.mark.parametrize("role", sorted(AVATAR_ROLES | RETIRED_ROLES))
def test_every_agent_publishes_its_avatar_url_to_agentverse(monkeypatch, role):
    import common
    monkeypatch.delenv("AGENT_AVATAR_BASE", raising=False)
    monkeypatch.setitem(common.SEEDS, role, "offline-private-example")
    url = common.agent_args(role, 8003)["avatar_url"]
    assert url == f"https://raw.githubusercontent.com/vs-githjk/cal-hacks-2026/main/agents/avatars/{role}.png"


def test_avatar_url_override_and_roles_without_a_file(monkeypatch):
    import common
    monkeypatch.setenv("AGENT_AVATAR_BASE", "https://example.test/av/")
    assert common.avatar_url("buyer") == "https://example.test/av/buyer.png"
    assert common.avatar_url("no_such_role") is None
    monkeypatch.setitem(common.SEEDS, "seller_1", "offline-private-example")
    assert common.agent_args("seller_1", 8011, avatar_url="https://x.test/a.png")["avatar_url"] == "https://x.test/a.png"
