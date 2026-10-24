"""held_out_v2.jsonl is frozen: its sha256 must equal the value recorded in HELD_OUT_V2.md, which was written
before any rule change in task T9. Editing the file (or the recorded hash) makes this test fail on purpose."""
import hashlib
import json
import os
import re

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "corpus")
SET = os.path.join(CORPUS, "held_out_v2.jsonl")
DOC = os.path.join(CORPUS, "HELD_OUT_V2.md")


def _recorded_sha() -> str:
    with open(DOC, encoding="utf-8") as f:
        m = re.search(r"sha256:\s*`([0-9a-f]{64})`", f.read())
    assert m, "HELD_OUT_V2.md must record the hash as: sha256: `<64 hex>`"
    return m.group(1)


def test_v2_file_matches_recorded_sha256():
    with open(SET, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == _recorded_sha(), "held_out_v2.jsonl is frozen, never edit it"


def test_v2_shape_and_size():
    with open(SET, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert all(r["label"] in ("attack", "clean") and isinstance(r["message"], str) for r in rows)
    assert sum(r["label"] == "attack" for r in rows) >= 30
    assert sum(r["label"] == "clean" for r in rows) >= 15
