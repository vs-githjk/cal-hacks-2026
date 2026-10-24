"""One honest line per sponsor: is it configured, when was it last called, what came back.

    python3 -m scripts.sponsor_status [--json web/public/sponsor-status.json] [--crs-cache <path>]

Reads each integration's own status() (Bright Data, Tiger Data) and the last CrsCheck record (CRS). It makes no
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

# Where the CRS adapter (Lane A, #15) leaves its most recent CrsCheck record. Nothing writes it until that lands,
# so today CRS reads "not configured" or "not called".
CRS_CACHE = ROOT / "data" / "crs_last_check.json"
CRS_ENV = ("CRS_USERNAME", "CRS_PASSWORD", "CRS_BASE_URL")
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


def _crs(cache: Path) -> dict:
    configured = all(os.environ.get(k, "").strip() for k in CRS_ENV)
    if not configured:
        return _row("CRS", False, None, "not_configured")
    try:
        record = json.loads(Path(cache).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _row("CRS", True, None, "not_called")
    except Exception:
        return _row("CRS", True, None, "error")
    try:
        from pay.crs_gate import validate_check
        if validate_check(record):
            return _row("CRS", True, None, "error")
        if record["origin"] == "NOT_CONFIGURED":
            return _row("CRS", True, record["checked_at"], "not_configured")
        return _row("CRS", True, record["checked_at"], "verified" if record["verified"] else "not_verified")
    except Exception:
        return _row("CRS", True, None, "error")


def collect(*, crs_cache: Optional[Path] = None) -> list[dict]:
    return [_bright_data(), _crs(Path(crs_cache) if crs_cache else CRS_CACHE), _tiger()]


def _yes_no(v: Optional[bool]) -> str:
    return "unknown" if v is None else ("yes" if v else "no")


def render(rows: list[dict]) -> str:
    width = max(len(r["name"]) for r in rows)
    return "\n".join(
        f"{r['name']:<{width}}  configured: {_yes_no(r['configured'])}  last call: {r['last_call'] or 'never'}  "
        f"result: {r['result'].replace('_', ' ')}"
        for r in rows)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="One honest status line per sponsor integration.")
    ap.add_argument("--json", metavar="PATH", help="also write the rows as JSON (for the web app)")
    ap.add_argument("--crs-cache", metavar="PATH", help="where the last CrsCheck record lives")
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
