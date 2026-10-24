"""Tests must never reach the network: drop the classifier switches before every test."""
import pytest


@pytest.fixture(autouse=True)
def _no_live_classifier(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)
