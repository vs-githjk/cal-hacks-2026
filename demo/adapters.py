"""Where the runner picks real code or a stand-in. When a lane merges, this is the only file that decides.

claim_check: data.claim_check.check_claim is used as-is when it accepts a `fetch` argument (Lane C's c3 does);
the always-unverified mock on today's branch lacks it, so the SIM stand-in runs and says so.
"""
from __future__ import annotations

import inspect
from typing import Callable


def claim_checker() -> tuple[Callable, str, bool]:
    """(check_claim, label, is_real)"""
    from data import claim_check as cc
    if "fetch" in inspect.signature(cc.check_claim).parameters:
        return cc.check_claim, "REAL data.claim_check (Lane C c3)", True
    from demo.standins.claim_check import check_claim
    return check_claim, "SIM stand-in demo/standins/claim_check.py (data.claim_check here is the always-unverified mock)", False
