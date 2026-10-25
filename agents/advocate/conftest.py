import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "buyer"))  # buyer/ for logic


import asyncio

import pytest


@pytest.fixture(autouse=True)
def _keep_a_current_event_loop():
    """asyncio.run in a test leaves no current loop, and building a uAgents Agent later needs one (test_status)."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
