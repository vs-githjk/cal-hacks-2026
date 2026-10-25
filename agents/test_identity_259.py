"""#259: agent display names under 20 characters, five-section READMEs, one avatar per agent (read from the files,
so no agent is constructed)."""
import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parent
SECTIONS = ("## Summary", "## Features", "## Usage examples", "## Use cases", "## Limitations")


@pytest.mark.parametrize("path,pattern", [
    ("advocate/advocate_agent.py", r'name="([^"]+)"'), ("shield_client.py", r"name='([^']+)'"),
    ("caller/caller_agent.py", r'NAME = "([^"]+)"'), ("buyer/buyer_agent.py", r'name="([^"]+)"'),
])
def test_display_names_match_agentverse_and_the_short_ones_are_under_20_characters(path, pattern):
    name = re.search(pattern, (AGENTS / path).read_text()).group(1)
    long_names = {"Tech Bazaar Quality Advocate", "Tech Bazaar Shield Client"}  # renamed on Agentverse (#383)
    assert name in long_names or len(name) < 20, name


@pytest.mark.parametrize("readme", ["advocate/AGENTVERSE.md", "SHIELD_AGENTVERSE.md", "caller/AGENTVERSE.md",
                                    "buyer/AGENTVERSE.md", *[f"sellers/AGENTVERSE-seller_{i}.md" for i in range(1, 6)]])
def test_every_readme_has_the_five_sections(readme):
    text = (AGENTS / readme).read_text()
    assert all(s in text for s in SECTIONS), [s for s in SECTIONS if s not in text]
    assert "—" not in text and "–" not in text


def test_one_png_avatar_per_agent_and_the_caller_is_pink():
    names = {"buyer", "advocate", "shield", "caller", *(f"seller_{i}" for i in range(1, 6))}
    for n in names:
        data = (AGENTS / "avatars" / f"{n}.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", n
    import zlib
    raw = (AGENTS / "avatars" / "caller.png").read_bytes()
    idat = raw[raw.index(b"IDAT") + 4: raw.index(b"IEND") - 8]
    first_pixel = zlib.decompress(idat)[1:4]
    assert tuple(first_pixel) == (255, 79, 163)


@pytest.mark.parametrize("role", ["buyer", "advocate", "shield", "caller", *(f"seller_{i}" for i in range(1, 6))])
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
    assert common.avatar_url("pulse") is None
    monkeypatch.setitem(common.SEEDS, "seller_1", "offline-private-example")
    assert common.agent_args("seller_1", 8011, avatar_url="https://x.test/a.png")["avatar_url"] == "https://x.test/a.png"
