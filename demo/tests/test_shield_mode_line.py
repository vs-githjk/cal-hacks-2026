"""Which Shield a demo run uses is printed at its start: the rule screen alone, or the rules plus the Claude classifier. The classifier is on only
when SHIELD_CLASSIFIER=1 and ANTHROPIC_API_KEY are both in the process environment (shield/classifier.py default_classifier); the runner's env
file feeds only the sponsor and Cartesia names, so a key there never turns it on."""
from __future__ import annotations

from demo import common
from shield import classifier


def test_the_default_run_is_the_rule_screen_and_says_how_to_turn_the_classifier_on():
    line = common.shield_mode_line({})
    assert "rule screen only" in line and "SHIELD_CLASSIFIER=1" in line and "ANTHROPIC_API_KEY" in line


def test_the_classifier_needs_both_names():
    assert "rule screen only" in common.shield_mode_line({"SHIELD_CLASSIFIER": "1"})
    assert "rule screen only" in common.shield_mode_line({"ANTHROPIC_API_KEY": "k"})
    assert "rule screen only" in common.shield_mode_line({"SHIELD_CLASSIFIER": "0", "ANTHROPIC_API_KEY": "k"})


def test_with_both_names_the_line_says_classifier_and_names_the_model_never_the_key():
    line = common.shield_mode_line({"SHIELD_CLASSIFIER": "1", "ANTHROPIC_API_KEY": "sk-secret-value"})
    assert "classifier" in line and classifier.DEFAULT_MODEL in line and "sk-secret-value" not in line and "rule screen only" not in line
    assert "my-model" in common.shield_mode_line({"SHIELD_CLASSIFIER": "1", "ANTHROPIC_API_KEY": "k", "SHIELD_MODEL": "my-model"})


def test_the_line_agrees_with_what_shield_itself_would_do(monkeypatch):
    for env in ({}, {"SHIELD_CLASSIFIER": "1"}, {"SHIELD_CLASSIFIER": "1", "ANTHROPIC_API_KEY": "k"}):
        for name in ("SHIELD_CLASSIFIER", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert (classifier.default_classifier() is not None) == ("rule screen only" not in common.shield_mode_line(env))


def test_shields_timeouts_are_untouched():
    assert classifier.TIMEOUT_S <= 2
