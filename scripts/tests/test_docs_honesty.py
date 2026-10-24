"""PITCH, REAL_VS_SIMULATED and SPONSORS tell only the truth (night run 2, T2). No network.

Run: python3 -m pytest scripts/tests/test_docs_honesty.py -q

README.md is owned by the main session on this run, so nothing here reads it. The README fixes live in
docs/README_CORRECTIONS.md for the main session to apply; that file is only checked for dashes.

What it pins, over docs/PITCH.md, docs/REAL_VS_SIMULATED.md and docs/SPONSORS.md:
  a. every line that names Bright Data, CRS, Tiger, the 3D floor, the "Hack the market" console, Interactive Cards
     or Claude either links a file that exists in this repo, or says planned, not built, in progress or not configured;
  b. every "N of M" or percent figure sits in a line that names an existing results file and a date, and the figure
     appears in that file;
  c. no em or en dash;
  d. the Cartesia section the track asks for (features used, setup, known limits) lives in SPONSORS.md;
  e. one goal price (under $1,300, winner $1,299.99 before sales tax) and no old $800 goal;
  f. Bright Data, CRS and Tiger carry one label everywhere (built, env-gated, not run live: the code is on this branch), and Tiger is never called live;
  g. nothing is called real that is not built (the teammate purchase), and no doc cites demo/README.md as proof.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ["docs/PITCH.md", "docs/REAL_VS_SIMULATED.md", "docs/SPONSORS.md"]
DASH_DOCS = DOCS + ["docs/README_CORRECTIONS.md"]

CLAIM = re.compile(r"Bright Data|\bCRS\b|Tiger|3D floor|Hack the market|Interactive Cards|Claude")
MARKER = re.compile(r"planned|not built|in progress|not configured|not called|not run live", re.I)
REF = re.compile(r"`([^`\s]+)`|\]\(([^)\s#]+)")
DASHES = ("—", "–")
FIGURE = re.compile(r"\d+ of \d+|\d+(?:\.\d+)?%")
DATE = re.compile(r"20\d\d-\d\d-\d\d")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def lines(doc_rel: str):
    yield from enumerate(read(doc_rel).splitlines(), 1)


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


@pytest.mark.parametrize("doc", DOCS)
def test_a_claims_are_built_with_a_link_or_labelled(doc):
    bad = []
    for n, line in lines(doc):
        if not CLAIM.search(line):
            continue
        if MARKER.search(line) or existing_refs(line, doc):
            continue
        bad.append(f"{doc}:{n}: {line.strip()[:140]}")
    assert not bad, "claim without an existing file link or a planned / not built / in progress label:\n" + "\n".join(bad)


@pytest.mark.parametrize("doc", DOCS)
def test_a_named_overclaims_only_appear_labelled(doc):
    bad = []
    for n, line in lines(doc):
        if re.search(r"Nothing is measured|Hack the market|Interactive Cards", line) and not re.search(r"not built|planned", line):
            bad.append(f"{doc}:{n}: {line.strip()[:140]}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("doc", DOCS)
def test_b_figures_come_from_a_named_dated_results_file(doc):
    bad = []
    for n, line in lines(doc):
        body = re.sub(r"`[^`]+`", " ", line)
        body = DATE.sub(" ", body)
        figures = FIGURE.findall(body)
        if not figures:
            continue
        paths = [p for p in re.findall(r"`([^`]+)`", line) if (ROOT / p).is_file() and re.search("RESULTS|ATTACKS", p.upper())]
        if not paths or not DATE.search(line):
            bad.append(f"{doc}:{n}: needs a results file and a date in the same line: {line.strip()[:120]}")
            continue
        source = "\n".join(read(p) for p in paths)
        for tok in figures:
            if tok not in source:
                bad.append(f"{doc}:{n}: {tok!r} is not in {paths}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("doc", DASH_DOCS)
def test_c_no_em_or_en_dash(doc):
    for ch in DASHES:
        assert ch not in read(doc), f"{doc} has a dash character U+{ord(ch):04X}"


def test_d_cartesia_section_in_sponsors():
    text = read("docs/SPONSORS.md")
    m = re.search(r"^#+ [^\n]*Cartesia[^\n]*\n.*?(?=^#+ |\Z)", text, re.S | re.M)
    assert m, "SPONSORS.md has no Cartesia section"
    sec = m.group(0)
    for needle in ("Features used", "Setup", "Known limits", "noisy", "pay/approval.py", "3 tries", "pay/voice_cartesia.py"):
        assert needle in sec, f"Cartesia section is missing {needle!r}"
    assert "9 of 10 denied on the first run" in sec and "v04 no longer blind" in sec
    assert not re.search(r"README has the Cartesia section", text), "SPONSORS.md still points at a README section"


def test_e_one_goal_price():
    for doc in ("docs/PITCH.md",):
        text = read(doc)
        assert "$800" not in text, f"{doc} still quotes the old $800 goal"
        assert "$1,299.99" in text and "before sales tax" in text and "under $1,300" in text
        assert "shipping: not captured" in text
    for doc in DOCS:
        assert "$800" not in read(doc)


STALE = ("is still a stub", "not on this branch", "no CRS code on this branch", "no code until", "night task T6 and not",
         "planned, not built: key set", "Tiger Data is planned", "CRS is planned", "CRS seller stability check | planned")


def test_f_bright_data_crs_and_tiger_are_built_env_gated_and_not_run_live():
    """T6, T8, T13, T15 and T16 are on this branch: the docs say built, env-gated, not run live, never stub or planned."""
    for doc in DOCS + ["docs/README_CORRECTIONS.md"]:
        text = read(doc)
        for old in STALE:
            assert old not in text, f"{doc} still says {old!r}, but that code is on this branch"
        for n, line in (lines(doc) if doc in DOCS else []):   # the corrections file only lists the checks, so it gets the stale-text check alone
            for seg in re.split(r"[.;]\s", line):
                if "Bright Data" in seg:
                    assert "planned" not in seg.lower() and "in progress" not in seg, f"{doc}:{n}: Bright Data is built, not planned or in progress"
                if re.search(r"\bTiger\b", seg):
                    assert not re.search(r"\bLIVE\b", seg), f"{doc}:{n}: Tiger has not been run live"
    sim = read("docs/REAL_VS_SIMULATED.md")
    rows = {k: next(ln for ln in sim.splitlines() if ln.startswith(k)) for k in
            ("| Bright Data", "| Seller stability and identity (CRS)", "| Tiger")}
    for k, row in rows.items():
        assert "built, env-gated, not run live (no key in the run)" in row, f"{k}: wrong label"
    assert "02:55" in rows["| Bright Data"] and "data/baselines/brightdata.py" in rows["| Bright Data"] and "0330-D-brightdata.md" in rows["| Bright Data"]
    assert "pay/crs_gate.py" in rows["| Seller stability and identity (CRS)"] and "0400-D-crs-payee.md" in rows["| Seller stability and identity (CRS)"]
    assert "02:53" in rows["| Tiger"] and "data/tiger/store.py" in rows["| Tiger"] and "0500-D-tiger.md" in rows["| Tiger"]
    for rel in ("data/baselines/brightdata.py", "pay/crs_gate.py", "data/tiger/store.py", "docs/changes/0330-D-brightdata.md",
                "docs/changes/0400-D-crs-payee.md", "docs/changes/0500-D-tiger.md"):
        assert (ROOT / rel).exists(), rel


def test_g_nothing_is_real_that_is_not_built():
    pitch = read("docs/PITCH.md")
    for n, line in lines("docs/PITCH.md"):
        if "teammate purchase" in line:
            assert re.search(r"planned|not built", line), f"docs/PITCH.md:{n}: the teammate purchase is not built"
        if "What is real" in line:
            assert "a teammate purchase" not in line
            assert "call client" in line and "approval judge" in line
    for n, line in lines("docs/PITCH.md"):
        if "real sellers really bid" in line.lower():
            assert "bids are real" not in line, f"docs/PITCH.md:{n}: no outside seller has bid; do not say bids are real"
    for n, line in lines("docs/SPONSORS.md"):
        if "Cartesia call" in line:
            assert "default and fallback" not in line, f"docs/SPONSORS.md:{n}: the in-browser Cartesia call is not built"
    corrections = read("docs/README_CORRECTIONS.md")
    status = corrections.split("## 3. Status", 1)[1].split("\n## ", 2)[1] if "## 3. Status" in corrections else ""
    assert "test_readme_honesty" not in status, "the pasted Status block cites a test that is not on this branch"
    assert "demo/README.md" not in pitch, "demo/README.md is run 1's file and still names the old winner"
    assert "demo/out/sample-run.json" in pitch and "demo/tests/test_demo_winner.py" in pitch


def test_h_pitch_stage_line_uses_the_locked_wording():
    """plan/decisions.md (LOCKED Sat 01:45): the Lot Wall line says request, not order (payment is Stripe test mode),
    and 'one or two bids here are real' is dropped (no outside seller has bid)."""
    locked = "This is one real request, Vidyut's. When many requests pool, this is what a seller sees."
    pitch = read("docs/PITCH.md")
    assert locked in pitch, "docs/PITCH.md must carry the LOCKED Lot Wall stage line exactly"
    for doc in DOCS:
        text = read(doc)
        for old in ("one real order", "many orders pool", "bids here are real", "one or two bids"):
            assert old not in text, f"{doc}: LOCKED stage-line wording dropped '{old}'"


def test_i_shield_numbers_on_the_two_frozen_files_are_first_run_figures():
    """T12 red team. test_b only checks that a figure appears somewhere in RESULTS.md, and '6 of 12' still does once lane-d-night
    is merged (RESULTS.md then says 'fresh12.jsonl 6 of 12 to 8 of 12 ... in-sample too'). The docs called that set 'run once, not
    tuned' and 'our best guess of real recall', which the merged RESULTS.md contradicts. A line that quotes the post-freeze
    check or the frozen probe must say it is the first run and no longer blind, and must not claim it was never tuned."""
    bad = []
    for doc in DASH_DOCS:
        for n, line in lines(doc):
            quotes = re.search(r"post-freeze|frozen probe|after we froze", line, re.I) and re.search(r"\b(?:6 of 12|6 of 10)\b", line)
            if not quotes:
                continue
            low = line.lower()
            if "first run" not in low or "no longer blind" not in low:
                bad.append(f"{doc}:{n}: say 'first run' and 'no longer blind': {line.strip()[:120]}")
            for old in ("not tuned", "run once", "best guess of real recall"):
                if old in low:
                    bad.append(f"{doc}:{n}: '{old}' is false once lane-d-night is merged: {line.strip()[:120]}")
    assert not bad, "\n".join(bad)
