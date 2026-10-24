"""One honest line per sponsor: is it configured, when was it last called, what came back.

    python3 -m scripts.sponsor_status [--json web/public/sponsor-status.json] [--crs-cache <path>]

Reads each integration's own status() (Bright Data, Tiger Data) and the newest signal in the CRS adapter's cache. It makes no
network call, opens no database connection and never prints an env value, a key, a URL or a CRS report field:
only the sponsor name, yes or no, an ISO time and a short result word. A status that fails becomes result "error"
with no message, so nothing it said can leak.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The CRS adapter (agents/crs.py, Lane A) caches its sandbox results here: supplier_id -> {persona_ref, signal, reason}.
# Only signal.checked_at and signal.stability are read; persona_ref and reason never leave this file.
CRS_CACHE = ROOT / ".cache" / "crs-signals.json"
# Configured means a bearer token, or both user and password, as the adapter's own _configured() decides
# (agents/crs.py: CRS_API_KEY or (CRS_USERNAME and CRS_PASSWORD)); CRS_BASE_URL is optional there.
CRS_ENV = ("CRS_USERNAME", "CRS_PASSWORD")
CRS_KEY = "CRS_API_KEY"
# The adapter loads this file through agents/common.py, so a credential kept here counts as set.
AGENTS_ENV = ROOT / "agents" / ".env"
# Bright Data and Tiger Data keep their status in module state, which a fresh CLI process does not have.
PER_PROCESS = ("Bright Data", "Tiger Data")
CRS_SOURCES = ("sandbox", "recorded")
NAMES = ("Bright Data", "CRS", "Tiger Data")


def _row(name: str, configured: Optional[bool], last_call: Optional[str], result: str) -> dict:
    return {"name": name, "configured": configured, "last_call": last_call, "result": result}


def _error(name: str) -> dict:
    return _row(name, None, None, "error")


def _from_status(name: str, st: dict) -> dict:
    configured = bool(st.get("configured"))
    result = st.get("last_result") or ("not_called" if configured else "not_configured")
    last_call = st.get("last_call")
    return _row(name, configured, last_call if isinstance(last_call, str) else None, str(result))


def _bright_data() -> dict:
    try:
        from data.baselines import brightdata
        return _from_status("Bright Data", brightdata.status())
    except Exception:
        return _error("Bright Data")


def _tiger() -> dict:
    try:
        from data.tiger import store
        return _from_status("Tiger Data", store.status())
    except Exception:
        return _error("Tiger Data")


def _parse_time(value: object) -> Optional[datetime]:
    """An ISO 8601 time as an aware datetime (naive counts as UTC), or None when it does not parse."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _newest_signal(cache: object) -> Optional[tuple]:
    """(checked_at text, stability) of the newest valid signal in the adapter's cache.

    None when no entry carries a signal; raises ValueError when signals exist but none is usable."""
    if not isinstance(cache, dict):
        raise ValueError("cache is not an object")
    seen, best = 0, None
    for entry in cache.values():
        signal = entry.get("signal") if isinstance(entry, dict) else None
        if signal is None:
            continue
        seen += 1
        if not isinstance(signal, dict):
            continue
        when = _parse_time(signal.get("checked_at"))
        stability = signal.get("stability")
        if when is None or signal.get("source") not in CRS_SOURCES or not isinstance(stability, str) or not stability:
            continue
        if best is None or when > best[0]:
            best = (when, signal["checked_at"], stability)
    if seen and best is None:
        raise ValueError("no usable signal")
    return None if best is None else (best[1], best[2])


def _env_file_values(path: Path) -> dict:
    """Name -> value from an env file, parsed as agents/common.py does (comments and empty values skipped).

    The values stay in this dict: nothing is put into os.environ and nothing is printed."""
    values: dict = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except Exception:
        return values
    for line in lines:
        key, _, val = line.partition("=")
        if key.strip() and not key.lstrip().startswith("#") and val.strip():
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _crs_env(name: str, file_values: dict) -> str:
    """A real environment variable wins over the file, as os.environ.setdefault does in the adapter."""
    return os.environ[name] if name in os.environ else file_values.get(name, "")


def _crs(cache: Path) -> dict:
    file_values = _env_file_values(AGENTS_ENV)
    configured = bool(_crs_env(CRS_KEY, file_values).strip()) or all(
        _crs_env(k, file_values).strip() for k in CRS_ENV)
    if not configured:
        return _row("CRS", False, None, "not_configured")
    try:
        data = json.loads(Path(cache).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _row("CRS", True, None, "not_called")
    except Exception:
        return _row("CRS", True, None, "error")
    try:
        newest = _newest_signal(data)
    except ValueError:
        return _row("CRS", True, None, "error")
    if newest is None:
        return _row("CRS", True, None, "not_called")
    checked_at, stability = newest
    return _row("CRS", True, checked_at, "verified" if stability == "verified_stable" else "not_verified")


def collect(*, crs_cache: Optional[Path] = None) -> list[dict]:
    return [_bright_data(), _crs(Path(crs_cache) if crs_cache else CRS_CACHE), _tiger()]


def _yes_no(v: Optional[bool]) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


def _last_call_text(r: dict) -> str:
    if r["last_call"]:
        return r["last_call"]
    return "none in this process" if r["name"] in PER_PROCESS else "never"


def render(rows: list[dict]) -> str:
    width = max(len(r["name"]) for r in rows)
    return "\n".join(
        f"{r['name']:<{width}}  configured: {_yes_no(r['configured'])}  last call: {_last_call_text(r)}  "
        f"result: {r['result'].replace('_', ' ')}"
        for r in rows)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="One honest status line per sponsor integration.")
    ap.add_argument("--json", metavar="PATH", help="also write the rows as JSON (for the web app)")
    ap.add_argument("--crs-cache", metavar="PATH", help="the CRS adapter cache (default .cache/crs-signals.json)")
    args = ap.parse_args(argv)
    rows = collect(crs_cache=Path(args.crs_cache) if args.crs_cache else None)
    print(render(rows))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.write_text(json.dumps({"generated_at": stamp, "sponsors": rows}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
