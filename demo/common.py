"""Shared helpers for the end-to-end demo runner: repo path, origin tags, contract validation, narrator.

Everything the runner prints that shows data carries an origin tag: LIVE (a real outside party right now),
MIRROR (our agent on a real, dated listing) or SIM (anything we generated). Code that is real but runs on SIM
data is still tagged SIM; the beat header says which code is real and which is a stand-in.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTRACTS = ROOT / "contracts"
SITE = ROOT / "data" / "liar_pages" / "site"
SNAPSHOTS = ROOT / "data" / "mirror" / "snapshots"
LIVE, MIRROR, SIM = "LIVE", "MIRROR", "SIM"
# Bid/Claim/Need `source` enum on this branch (contracts/) is lower case.
SOURCE_OF = {LIVE: "live", MIRROR: "mirror", SIM: "simulated"}
PAGE_BASE = "http://127.0.0.1:8765/"  # python3 -m http.server 8765 --directory data/liar_pages/site


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_schema(name: str) -> dict:
    """contracts/<name>.schema.json: every contract the demo uses is on main now."""
    path = CONTRACTS / f"{name}.schema.json"
    if not path.exists():
        raise FileNotFoundError(f"no schema for contract {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def schema_errors(name: str, obj: Any) -> list[str]:
    from jsonschema import Draft202012Validator
    errs = Draft202012Validator(load_schema(name)).iter_errors(obj)
    return sorted(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errs)


def validate(name: str, obj: Any) -> Any:
    """Raise ValueError if `obj` breaks the contract; return it unchanged otherwise."""
    errors = schema_errors(name, obj)
    if errors:
        raise ValueError(f"{name} contract violated: " + "; ".join(errors))
    return obj


def shield_mode_line(environ: Optional[dict] = None) -> str:
    """One console line saying which Shield screens this run: the deterministic rules alone, or the rules plus the Claude classifier.
    Mirrors shield.classifier.default_classifier (both SHIELD_CLASSIFIER=1 and ANTHROPIC_API_KEY in the process environment). Names only."""
    import os
    from shield import classifier
    env = os.environ if environ is None else environ
    if env.get("SHIELD_CLASSIFIER") == "1" and env.get("ANTHROPIC_API_KEY"):
        return f"Shield: rules plus the Claude classifier ({env.get('SHIELD_MODEL') or classifier.DEFAULT_MODEL}); it can only add a quarantine"
    return ("Shield: rule screen only. To add the Claude classifier, export SHIELD_CLASSIFIER=1 and ANTHROPIC_API_KEY in the shell that runs this "
            "(the env file is not read for them)")


def money(x: float) -> str:
    return f"${x:,.2f}"


class Narrator:
    """The console story: one header per beat, one tagged line per fact. `show=False` runs silently."""

    def __init__(self, show: bool = True, stream: Optional[TextIO] = None):
        self.show = show
        self.stream = stream or sys.stdout

    def _w(self, text: str) -> None:
        if self.show:
            print(text, file=self.stream)

    def header(self, n: int, title: str, code: str) -> None:
        self._w("")
        self._w("=" * 78)
        self._w(f"BEAT {n}: {title}")
        self._w(f"  code: {code}")
        self._w("=" * 78)

    def line(self, origin: Optional[str], text: str, indent: int = 0) -> None:
        tag = f"[{origin}]" if origin else ""
        self._w(f"  {tag:<9}{'  ' * indent}{text}")

    def note(self, text: str) -> None:
        self._w(f"  {'':<9}{text}")

    def blank(self) -> None:
        self._w("")

    def quiet(self) -> "Narrator":
        return Narrator(False, self.stream)
