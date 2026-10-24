"""Demo tests are offline: a BRIGHT_DATA_API_KEY in the shell must never turn beat 4's live re-check on."""
import pytest


@pytest.fixture(autouse=True)
def _no_bright_data_key(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)
