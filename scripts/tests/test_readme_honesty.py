"""README, PITCH, REAL_VS_SIMULATED and SPONSORS tell only the truth (night run 2, T2). No network.

Run: python3 -m pytest scripts/tests/test_readme_honesty.py -q

What it pins:
  a. every line that names Bright Data, CRS, Tiger, the 3D floor, the "Hack the market" console, Interactive Cards
     or Claude either links a file that exists in this repo, or says planned, not built, in progress or not configured;
  b. the Numbers section quotes only numbers that appear in the results file its row names, each with a date;
  c. no em or en dash in the four docs;
  d. the Status table never says planned for a piece whose code exists, and never says built without existing code;
  e. the Fetch.ai rows are byte-identical to the fork point with origin/main (Abhinav's #95 edits them);
  f. one goal price everywhere (under $1,300, winner $1,299.99 before sales tax) and the top honesty line;
  g. the Cartesia section the track asks for.
"""
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["README.md", "docs/PITCH.md", "docs/REAL_VS_SIMULATED.md", "docs/SPONSORS.md"]

CLAIM = re.compile(r"Bright Data|\bCRS\b|Tiger|3D floor|Hack the market|Interactive Cards|Claude")
MARKER = re.compile(r"planned|not built|in progress|not configured|not called", re.I)
REF = re.compile(r"`([^`\s]+)`|\]\(([^)\s#]+)")
DASHES = ("—", "–")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fetch_blocks(text: str) -> list[str]:
    """The README parts that belong to Abhinav's #95: sponsor rows that start with | Fetch.ai | and the
    '## Fetch.ai agents' section up to the next heading."""
    blocks = [ln for ln in text.splitlines() if ln.startswith("| Fetch.ai |")]
    m = re.search(r"^## Fetch\.ai agents\n.*?(?=^## )", text, re.S | re.M)
    if m:
        blocks.append(m.group(0))
    return blocks


def existing_refs(line: str, doc_rel: str) -> list[str]:
    out = []
    for a, b in REF.findall(line):
        ref = (a or b).strip().rstrip(".,;:")
        if ref.startswith(("http://", "https://", "/")) or "/" not in ref and "." not in ref:
            continue
        for base in (ROOT, (ROOT / doc_rel).parent):
            if (base / ref).exists():
                out.append(ref)
                break
    return out


def claim_lines(doc_rel: str):
    text = read(doc_rel)
    skip = set()
    if doc_rel == "README.md":
        for block in fetch_blocks(text):
            skip.update(block.splitlines())
    for n, line in enumerate(text.splitlines(), 1):
        if line not in skip:
            yield n, line


@pytest.mark.parametrize("doc", DOCS)
def test_a_claims_are_built_with_a_link_or_labelled(doc):
    bad = []
    for n, line in claim_lines(doc):
        if not CLAIM.search(line):
            continue
        if MARKER.search(line) or existing_refs(line, doc):
            continue
        bad.append(f"{doc}:{n}: {line.strip()[:140]}")
    assert not bad, "claim without an existing file link or a planned / not built / in progress label:\n" + "\n".join(bad)


@pytest.mark.parametrize("doc", ["README.md", "docs/PITCH.md"])
def test_a_named_overclaims_only_appear_labelled(doc):
    bad = []
    for n, line in claim_lines(doc):
        if re.search(r"Nothing is measured|Hack the market|Interactive Cards", line) and not re.search(r"not built|planned", line):
            bad.append(f"{doc}:{n}: {line.strip()[:140]}")
    assert not bad, "\n".join(bad)


def numbers_rows():
    text = read("README.md")
    m = re.search(r"^## Numbers.*?(?=^## )", text, re.S | re.M)
    assert m, "README has no Numbers section"
    rows = [ln for ln in m.group(0).splitlines() if ln.startswith("|") and not re.match(r"\|[\s\-|]+\|$", ln)]
    return m.group(0), rows[1:]  # drop the header row


def test_b_numbers_section_quotes_only_named_results():
    section, rows = numbers_rows()
    assert "Nothing is measured yet" not in read("README.md")
    assert len(rows) >= 5, "expected one row per measured thing"
    num = re.compile(r"\d+ of \d+|\d+(?:\.\d+)?%|\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)? ms")
    for row in rows:
        paths = [p for p in re.findall(r"`([^`]+)`", row) if (ROOT / p).is_file()]
        assert paths, f"row names no existing results file: {row[:100]}"
        assert re.search(r"20\d\d-\d\d-\d\d", row), f"row has no date: {row[:100]}"
        source_text = "\n".join(read(p) for p in paths)
        body = re.sub(r"`[^`]+`", " ", row)
        body = re.sub(r"20\d\d-\d\d-\d\d", " ", body)
        for tok in num.findall(body):
            assert tok in source_text, f"{tok!r} is not in {paths}: {row[:100]}"
    # results that show no effect are reported too
    assert re.search(r"no headline lift|no lift", section, re.I)


@pytest.mark.parametrize("doc", ["README.md", "docs/PITCH.md", "docs/REAL_VS_SIMULATED.md", "docs/SPONSORS.md"])
def test_c_no_em_or_en_dash(doc):
    for ch in DASHES:
        assert ch not in read(doc), f"{doc} has a dash character U+{ord(ch):04X}"


def status_rows():
    text = read("README.md")
    m = re.search(r"^## Status\n.*?(?=^## )", text, re.S | re.M)
    assert m, "README has no Status section"
    rows = [ln for ln in m.group(0).splitlines() if ln.startswith("|") and not re.match(r"\|[\s\-|]+\|$", ln)]
    header, rows = rows[0], rows[1:]
    assert [c.strip() for c in header.strip("|").split("|")] == ["Piece", "State", "Code"]
    return [[c.strip() for c in r.strip("|").split("|")] for r in rows]


def test_d_status_table_matches_the_code():
    rows = status_rows()
    assert len(rows) >= 15
    for piece, state, code in rows:
        paths = re.findall(r"`([^`]+)`", code)
        exist = [p for p in paths if (ROOT / p).exists()]
        if state.startswith("planned"):
            assert not exist, f"'{piece}' says planned but {exist} exists on this branch"
        elif state.startswith("built"):
            assert paths and len(exist) == len(paths), f"'{piece}' says built but a path is missing: {paths}"
        else:
            assert state.startswith("in progress"), f"'{piece}': state must start with planned, in progress or built"
            assert all((ROOT / p).exists() for p in paths), f"'{piece}' names a path that does not exist: {paths}"


def test_e_fetch_rows_are_byte_identical_to_the_fork_point():
    try:
        base = subprocess.run(["git", "-C", str(ROOT), "merge-base", "HEAD", "origin/main"], capture_output=True,
                              text=True, check=True).stdout.strip()
        old = subprocess.run(["git", "-C", str(ROOT), "show", f"{base}:README.md"], capture_output=True,
                             text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("no origin/main to compare with")
    assert fetch_blocks(old), "fork-point README has no Fetch.ai rows (the test would pass for nothing)"
    assert fetch_blocks(read("README.md")) == fetch_blocks(old)


def test_f_one_goal_price_and_the_honesty_line():
    for doc in ("README.md", "docs/PITCH.md"):
        text = read(doc)
        assert "$800" not in text, f"{doc} still quotes the old $800 goal"
        assert "$1,299.99" in text and "before sales tax" in text, f"{doc} must state the winner and 'before sales tax'"
        assert "under $1,300" in text
        assert "shipping: not captured" in text
    top = "\n".join(read("README.md").splitlines()[:24])
    assert "Store prices are real dated mirrors; the bidding agents are ours (SIM) until a shop runs the Seller Kit." in top


def test_g_cartesia_section():
    text = read("README.md")
    m = re.search(r"^## [^\n]*Cartesia[^\n]*\n.*?(?=^## )", text, re.S | re.M)
    assert m, "README has no Cartesia section"
    sec = m.group(0)
    for needle in ("Features used", "Setup", "Known limits", "noisy", "pay/approval.py", "3 tries", "pay/voice_cartesia.py"):
        assert needle in sec, f"Cartesia section is missing {needle!r}"
