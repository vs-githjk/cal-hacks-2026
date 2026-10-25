import pytest


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    """Buyer tests never reach the network: goal understanding falls back to the regex reader unless a test passes its own.
    The Buyer's chat memory is process-wide, so every test starts with it empty."""
    monkeypatch.setenv("BUYER_UNDERSTAND_LLM", "0")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)  # no buyer test may reach Stripe, even from a developer shell
    try:
        import memory
        memory.MEMORY._rows.clear()
    except ImportError:
        pass
