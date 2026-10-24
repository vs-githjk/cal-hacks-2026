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
