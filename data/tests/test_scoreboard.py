import json
from pathlib import Path

from jsonschema import validate

from data.scoreboard import build

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "Scoreboard.schema.json").read_text())


def test_scoreboard_matches_contract_and_has_four_tiles():
    sb = build()
    validate(sb, SCHEMA)
    assert [t["id"] for t in sb["tiles"]] == ["verified_savings", "attacks_blocked", "fit_accuracy", "learning_lift"]


def test_no_number_without_its_source_run_and_label():
    for t in build()["tiles"]:
        assert t["source_run"].startswith("python3 -m ") and t["origin"] in ("LIVE", "MIRROR", "SIM")
        if t["status"] != "measured":
            assert t["value"] is None, t["id"]


def test_honest_states_today():
    tiles = {t["id"]: t for t in build()["tiles"]}
    assert tiles["verified_savings"]["status"] == "none_yet"           # no was-price claims captured
    assert tiles["learning_lift"]["status"] == "not_quotable"           # gate needs 2 winning archetypes
    assert tiles["attacks_blocked"]["detail"]["held_out"]["attacks"] == 20
    assert tiles["attacks_blocked"]["value"] == tiles["attacks_blocked"]["detail"]["held_out"]["block_rate"]  # held-out, never pooled
    assert tiles["fit_accuracy"]["detail"]["false_ok"] == 0


def test_every_date_range_runs_forwards():
    for t in build()["tiles"]:
        assert t["date_range"]["from"][:10] <= t["date_range"]["to"][:10], (t["id"], t["date_range"])


def test_learning_claim_always_shows_the_untrained_learner():
    tile = next(t for t in build()["tiles"] if t["id"] == "learning_lift")
    assert "untrained" in tile["note"]
