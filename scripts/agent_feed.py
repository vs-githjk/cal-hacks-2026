"""Agent feed: what the Fetch agents are doing, read from the launcher's own run dir (pids.json and .run/logs).

GET /v1/agents -> [{name, role, address, status, last_message, at, origin}]

status is "agentverse" only when the launcher started that agent in mailbox mode, the process is alive and its log shows
no failed manifest publish; "local" when it is alive without that; "down" otherwise (also when its log is missing).
Nothing here is invented: a missing run dir, pidfile or log gives down rows with no address and no message.
`at` is the log file's modification time, given only to the agent whose line is the last one in that file (logs carry no
per-line clock), so a shared Bureau log never stamps a quiet agent with another agent's time.

Run (the launcher does this): python3 -m uvicorn agent_feed:app --app-dir scripts --host 127.0.0.1 --port 8790
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launch  # noqa: E402  (stdlib-only launcher: pidfile reader and liveness check)

REPO = Path(__file__).resolve().parent.parent
MAX_MESSAGE = 140
ROLES = {"buyer": "buyer", "advocate": "advocate", "sellers": "seller"}
DEFAULT_NAMES = {"buyer": "Tech Bazaar Buyer", "advocate": "Tech Bazaar Quality Advocate", "sellers": "Seller agents"}

LINE_RE = re.compile(r"^(?:INFO|WARNING|ERROR|CRITICAL|DEBUG):\s+\[([^\]]+)\]: (.*)$")
START_RE = re.compile(r"Starting agent with address: (agent1q[0-9a-z]{40,70})")
LABEL_RE = re.compile(r"^(\w+) address: (agent1q[0-9a-z]{40,70})\s*$")
# lines about boot and registration, never a message the agent sent or received
NOISE = ("Starting agent", "Starting server", "inspector", "Manifest published", "registration", "Registration", "Almanac",
         "wallet", "Overwriting", "endpoint", "Unable to publish manifest")
# machine records that are long and carry mandate or order fields
RECORD_PREFIXES = ("ORDER ", "MANDATE ")
SECRET_RE = re.compile(r"\b(?:sk|pk|rk|whsec)_[A-Za-z0-9_]{6,}|eyJ[A-Za-z0-9_-]{10,}|Bearer\s+\S+", re.I)
PUBLISH_FAILED = "Unable to publish manifest"


def clean(text: str) -> str:
    text = SECRET_RE.sub("[hidden]", text).strip()
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 3] + "..."


def read_text(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_log(text: str) -> dict[str, dict]:
    """Agents in one log: {tag: {address, last_message, last_index}}; last_index orders messages across agents."""
    agents: dict[str, dict] = {}
    labels: dict[str, str] = {}  # address -> label ("seller_1 address: ...")
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        lab = LABEL_RE.match(line)
        if lab:
            labels[lab.group(2)] = lab.group(1)
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        tag, msg = m.group(1), m.group(2)
        if tag.startswith("uagents") or tag == "bureau":
            continue
        a = agents.setdefault(tag, {"address": None, "last_message": None, "last_index": -1})
        s = START_RE.search(msg)
        if s:
            a["address"] = s.group(1)
        if any(n in msg for n in NOISE) or msg.startswith(RECORD_PREFIXES):
            continue
        a["last_message"] = clean(msg)
        a["last_index"] = i
    for addr, label in labels.items():  # an agent that only printed its labelled address still gets a row
        if not any(a["address"] == addr for a in agents.values()):
            agents.setdefault(label, {"address": addr, "last_message": None, "last_index": -1})
    return agents


def _mtime_iso(path: str) -> str | None:
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _row(name, role, address, status, message, at) -> dict:
    return {"name": name, "role": role, "address": address, "status": status, "last_message": message, "at": at,
            "origin": "LIVE" if status != "down" else "SIM"}


def service_rows(svc: str, rec: dict) -> list[dict]:
    role = ROLES[svc]
    label, _ = launch.evaluate(rec)
    alive = label == "UP"
    text = read_text(rec.get("log"))
    if label in ("SKIPPED", "FAILED"):
        return [_row(DEFAULT_NAMES[svc], role, None, "down", clean(rec.get("reason", "")) or None, None)]
    if text is None:
        return [_row(DEFAULT_NAMES[svc], role, None, "down", None, None)]
    agents = parse_log(text)
    if not agents:
        return [_row(DEFAULT_NAMES[svc], role, None, "down", None, None)]
    status = "local" if alive else "down"
    if alive and rec.get("mailbox") is True and PUBLISH_FAILED not in text:
        status = "agentverse"
    newest = max(agents, key=lambda t: agents[t]["last_index"])
    mtime = _mtime_iso(rec["log"])
    rows = []
    for tag, a in agents.items():
        stamped = mtime if (tag == newest and a["last_message"] is not None) else None
        rows.append(_row(tag, role, a["address"], status, a["last_message"], stamped))
    return rows


def agent_rows(run_dir: Path | str) -> list[dict]:
    """One row per agent the launcher started; the three default roles as down rows when nothing is known."""
    try:
        services = launch.PidFile(Path(run_dir)).load().get("services", {})
        if not isinstance(services, dict):
            services = {}
    except Exception:  # a hand-edited pidfile must not take the feed down
        services = {}
    rows: list[dict] = []
    for svc in ROLES:
        rec = services.get(svc)
        if not isinstance(rec, dict):
            rows.append(_row(DEFAULT_NAMES[svc], ROLES[svc], None, "down", None, None))
            continue
        try:
            rows.extend(service_rows(svc, rec))
        except Exception:
            rows.append(_row(DEFAULT_NAMES[svc], ROLES[svc], None, "down", None, None))
    return rows


def create_app(run_dir: Path | str | None = None):
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    run = Path(run_dir or os.environ.get("AGENT_FEED_RUN_DIR") or REPO / ".run")
    app = FastAPI(title="Tech Bazaar agent feed", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$", allow_methods=["GET"],
                       allow_headers=[])

    @app.get("/v1/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/v1/agents")
    def agents() -> list[dict]:
        return agent_rows(run)

    return app


app = create_app()
