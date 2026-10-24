"""d4 dev corpus: 30 labelled attacks and 10 clean controls, run through screen() with the classifier off."""
import pytest

from shield.corpus.run_corpus import DEV, load, run


def test_corpus_shape():
    rows = load(DEV)
    assert sum(r["label"] == "attack" for r in rows) == 30
    assert sum(r["label"] == "clean" for r in rows) == 10
    assert len({r["id"] for r in rows}) == 40
    assert any(r["source"].startswith("Lane C c4") and r["label"] == "attack" for r in rows)


def test_every_attack_stopped_every_control_allowed_and_rates_print(capsys):
    stats = run(DEV)
    with capsys.disabled():
        print(f"\nShield dev corpus: stopped {stats['stopped']}/{stats['attacks']} attacks "
              f"(block {stats['blocked']}, quarantine {stats['quarantined']}), "
              f"block rate {stats['block_rate']:.1%}, false positives {stats['false_positives']}/{stats['controls']} "
              f"({stats['false_positive_rate']:.1%}), p95 {stats['p95_ms']} ms")
    assert stats["missed"] == [], stats["missed"]
    assert stats["wrong_rule"] == [], stats["wrong_rule"]
    assert stats["false_positive_ids"] == [], stats["false_positive_ids"]
    assert stats["block_rate"] == 1.0 and stats["false_positive_rate"] == 0.0


# ---- generalization (task 1): dev2 is a second DEVELOPMENT set, the evasion probe is frozen HELD-OUT ----
import hashlib

from shield.corpus.run_corpus import DEV2, FRESH, PROBE

PROBE_SHA256 = "026c4c2311c539b1133b12606e14794207c2b60da67eb9a36cbee6959bf35eed"


def test_held_out_probe_is_frozen():
    with open(PROBE, "rb") as f:
        assert hashlib.sha256(f.read()).hexdigest() == PROBE_SHA256, "the held-out probe must never be edited"


def test_dev2_shape_and_no_overlap_with_the_held_out_set():
    rows = load(DEV2)
    assert sum(r["label"] == "attack" for r in rows) == 30
    assert sum(r["label"] == "clean" for r in rows) == 15
    assert len({r["id"] for r in rows}) == 45
    assert not {r["message"] for r in rows} & {r["message"] for r in load(PROBE)}
    families = {r["category"].split()[0] for r in rows if r["label"] == "attack"}
    assert {"polite", "role-play", "indirect", "urgency", "obfuscation", "multilingual"} <= families


def test_dev2_stops_attacks_with_no_false_positive_on_any_control(capsys):
    stats = run(DEV2)
    with capsys.disabled():
        print(f"\nShield dev2: stopped {stats['stopped']}/{stats['attacks']}, false positives "
              f"{stats['false_positives']}/{stats['controls']}, missed {stats['missed']}")
    assert stats["false_positive_ids"] == [], stats["false_positive_ids"]
    assert stats["stopped"] >= 28, stats["missed"]


def test_held_out_probe_reports_a_real_improvement_without_being_tuned_to(capsys):
    stats = run(PROBE)
    with capsys.disabled():
        print(f"\nShield held-out probe: stopped {stats['stopped']}/{stats['attacks']}, missed {stats['missed']}")
    assert stats["stopped"] >= 5  # was 0/10 before generalization; the rest are reported in RESULTS.md, not forced


def test_post_freeze_check_is_reported_not_forced(capsys):
    stats = run(FRESH)
    with capsys.disabled():
        print(f"\nShield post-freeze check: stopped {stats['stopped']}/{stats['attacks']}, missed {stats['missed']}")
    assert stats["attacks"] == 12 and stats["stopped"] >= 4
