"""Where the runner picks real code. Every lane that matters is on main now, so this file only loads it.

claim_check: Lane C's real data.claim_check.check_claim, offline (the runner passes a fixture fetch that reads
data/liar_pages/site from disk, so no server and no network).

advocate: Lane A's real agents/advocate/checks.py (advise, call_reason, CALL_SUMMARIES). The file does
`import common`, and agents/common.py imports the uagents runtime, which is not installed here. checks.py uses
`common` for one thing only: putting the repo root on sys.path. So when the real `common` cannot be imported, the
file is loaded with an empty stand-in for that one module name; no function of checks.py is copied or changed.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from functools import lru_cache
from typing import Callable

from demo.common import ROOT

CHECKS_PATH = ROOT / "agents" / "advocate" / "checks.py"


def claim_checker() -> tuple[Callable, str, bool]:
    """(check_claim, label, is_real)"""
    from data.claim_check import check_claim
    return check_claim, "REAL data.claim_check (Lane C), offline via fixture fetch", True


@lru_cache(maxsize=1)
def advocate_checks() -> tuple[types.ModuleType, str]:
    """(module, how it was loaded). The module is Lane A's real checks.py either way."""
    spec = importlib.util.spec_from_file_location("lane_a_advocate_checks", CHECKS_PATH)
    mod = importlib.util.module_from_spec(spec)
    had = "common" in sys.modules
    how = "REAL agents/advocate/checks.py"
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as e:
        if e.name not in ("uagents", "common"):
            raise
        for name in [n for n in sys.modules if n == "common" or n.startswith("lane_a_advocate_checks")]:
            sys.modules.pop(name, None)
        sys.modules["common"] = types.ModuleType("common")      # checks.py uses it only to set sys.path
        try:
            spec.loader.exec_module(mod)
        finally:
            if not had:
                sys.modules.pop("common", None)
        how += " (uagents runtime not installed: the one `import common` line is satisfied by an empty module)"
    return mod, how
