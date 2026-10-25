"""No test reaches the network: the readiness read of a new shop's listing pages (#398) is a stub unless a test sets one."""
import pytest

from seller_kit import api


@pytest.fixture(autouse=True)
def no_live_readiness(monkeypatch):
    calls = []

    def stub(url, fetch=None, now=None):
        calls.append(url)
        return {"url": url, "status": "unreadable", "summary": "stub: not read in tests", "findings": [], "origin": "SIM"}
    monkeypatch.setattr(api, "check_listing", stub)
    return calls
