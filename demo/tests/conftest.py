"""Demo tests are offline: a BRIGHT_DATA_API_KEY in the shell must never turn beat 4's live re-check on."""
import pytest


@pytest.fixture(autouse=True)
def _no_bright_data_key(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_shield_classifier(monkeypatch):
    """Keyed shells must not turn the live Claude classifier on inside the offline demo tests (module-scoped fixtures
    that need a classifier patch shield.core.default_classifier with a stub instead)."""
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)
