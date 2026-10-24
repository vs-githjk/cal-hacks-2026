"""Which SpacetimeDB market the bridge, the stage and the rehearsal talk to (#295): local by default, Maincloud when the
Lane D env file says so.

Three names, read from the process environment first and then from the Lane D env file (never overriding the process):
  SPACETIMEDB_SERVER  the `spacetime -s` server: "local" (default), "maincloud", or an http(s) URL
  SPACETIMEDB_HTTP    the HTTP API the Python clients call (market/scripts/stdb.py): default http://127.0.0.1:3000
  SPACETIMEDB_DB      the database name (default tech-bazaar)

Role tokens are per market. A local run keeps using .tokens/ as before. Any other market uses .tokens/<db>@<host>/ only
and never falls back to the local tokens, so a local identity never signs a call on the shared Maincloud market (or the
other way round). A target that does not parse is refused before any call.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("SPACETIMEDB_SERVER", "SPACETIMEDB_HTTP", "SPACETIMEDB_DB")
DEFAULTS = {"SPACETIMEDB_SERVER": "local", "SPACETIMEDB_HTTP": "http://127.0.0.1:3000", "SPACETIMEDB_DB": "tech-bazaar"}
_DB = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_SERVER = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class TargetError(ValueError):
    """The market target does not parse; nothing is called."""


def _file_values(env_file: Optional[Path]) -> dict:
    if env_file is None or not Path(env_file).expanduser().is_file():
        return {}
    out = {}
    for line in Path(env_file).expanduser().read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k.strip() in NAMES and not line.lstrip().startswith("#"):
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve(env_file: Optional[Path] = None, environ: Mapping[str, str] = os.environ) -> dict:
    """{server, http, db, local} for this run, or TargetError."""
    vals = {**DEFAULTS, **{k: v for k, v in _file_values(env_file).items() if v}, **{k: environ[k] for k in NAMES if environ.get(k)}}
    server, http, db = vals["SPACETIMEDB_SERVER"].strip(), vals["SPACETIMEDB_HTTP"].strip().rstrip("/"), vals["SPACETIMEDB_DB"].strip()
    if not _DB.fullmatch(db):
        raise TargetError(f"SPACETIMEDB_DB {db[:40]!r} is not a database name (lowercase letters, digits and -)")
    parts = urlsplit(http)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.path not in ("", "/"):
        raise TargetError("SPACETIMEDB_HTTP must be a plain http(s) origin, like https://maincloud.spacetimedb.com")
    if not (_SERVER.fullmatch(server) or urlsplit(server).scheme in ("http", "https")):
        raise TargetError(f"SPACETIMEDB_SERVER {server[:40]!r} is not a server name or URL")
    local = server == "local" and parts.hostname in _LOCAL_HOSTS
    if not local and parts.scheme != "https":
        raise TargetError("a market that is not local must be reached over https (SPACETIMEDB_HTTP)")
    if server == "local" and not local:
        raise TargetError("SPACETIMEDB_SERVER is local but SPACETIMEDB_HTTP is another host: set both to the same market")
    return {"server": server, "http": http, "db": db, "local": local}


def export(target: dict) -> None:
    """Put the target where market/scripts/stdb.py reads it (at import), for this process and its children."""
    os.environ["SPACETIMEDB_SERVER"] = target["server"]
    os.environ["SPACETIMEDB_HTTP"] = target["http"]
    os.environ["SPACETIMEDB_DB"] = target["db"]


def tokens_dir(target: dict, root: Optional[Path] = None) -> Path:
    """The folder for this market's role tokens: .tokens/ for the local market, .tokens/<db>@<host>/ for any other."""
    root = root or ROOT
    if target["local"]:
        return root / ".tokens"
    return root / ".tokens" / f"{target['db']}@{urlsplit(target['http']).hostname}"


def describe(target: dict) -> str:
    where = "local SpacetimeDB" if target["local"] else f"shared market at {urlsplit(target['http']).hostname}"
    return f"market: {target['db']} on {where} (spacetime -s {target['server']})"
