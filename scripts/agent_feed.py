"""Agent feed: what the Fetch agents are doing, read from the launcher's own run dir (pids.json and .run/logs).

GET /v1/agents -> [{name, role, address, status, last_message, at, origin}]
GET /v1/memory -> {entries: [MemoryEntry], sources, note} for the dashboard memory panel (#189, demo/memory.py):
past goals, purchases, vetoes and seller lessons from demo/out (MEMORY_DIR overrides). ?kind=, ?limit=, ?sample=1.

status is decided per agent from its own log lines, never from a pidfile flag: "agentverse" only when the process is alive
and that agent logged "Starting mailbox client for" (the uagents mailbox loop running) and none of the mailbox or manifest
failure lines (no mailbox created yet, cannot reach the mailbox server, 401 on retrieve, manifest not published); "local" when
it is alive without that; "down" otherwise (also when its log is missing). A mailbox created by connect.py after the agent
started logs one unattributed [mailbox] "Successfully registered" line: it clears "mailbox not found" only for the single
agent waiting on one when no other agent in the log runs a mailbox client; otherwise they stay as they are (cannot say which). Only tags that logged "Starting agent with
address" are agents, so uagents module loggers (resolver, dispenser, mailbox ...) never become rows. Manifests publish fine without a mailbox, so a
published manifest proves nothing about Agentverse.
Nothing here is invented: a missing run dir, pidfile or log gives down rows with no address and no message.
origin is SIM for every row except a seller whose sellers.json entry says otherwise: our own agents are not "LIVE" (a real
outside party), and an unknown seller is SIM.
`at` is the log file's modification time, given only to the agent whose line is the last line in that file (logs carry no
per-line clock): if any other line of any kind follows its message, `at` is null, so a shared Bureau log or an hourly
Almanac re-registration never stamps an old or quiet agent with a fresh time.

Run (the launcher does this): python3 -m uvicorn agent_feed:app --app-dir scripts --host 127.0.0.1 --port 8790
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent))  # the repo root, for demo.memory
import launch  # noqa: E402  (stdlib-only launcher: pidfile reader and liveness check)

REPO = Path(__file__).resolve().parent.parent
MAX_MESSAGE = 140
ROLES = {"buyer": "buyer", "advocate": "advocate", "sellers": "seller"}
DEFAULT_NAMES = {"buyer": "Tech Bazaar Buyer", "advocate": "Bazaar Advocate", "sellers": "Seller agents"}

LINE_RE = re.compile(r"^(?:INFO|WARNING|ERROR|CRITICAL|DEBUG):\s+\[([^\]]+)\]: (.*)$")
START_RE = re.compile(r"Starting agent with address: (agent1q[0-9a-z]{40,70})")
LABEL_RE = re.compile(r"^(\w+) address: (agent1q[0-9a-z]{40,70})\s*$")
# lines about boot and registration, never a message the agent sent or received
NOISE = ("Starting agent", "Starting server", "Agent inspector available", "Manifest published", "registration", "Registration",
         "Almanac", "wallet", "Overwriting", "endpoint", "Unable to publish manifest", "Starting mailbox client")
# machine records that are long and carry mandate or order fields
RECORD_PREFIXES = ("ORDER ", "MANDATE ")
SECRET_RE = re.compile(r"\b(?:sk|pk|rk|whsec)_[A-Za-z0-9_]{6,}|eyJ[A-Za-z0-9_-]{10,}|Bearer\s+\S+", re.I)
# uagents mailbox.py:214 (the loop running) and the lines that say the mailbox is not working (mailbox.py:238, 243, 247, agent.py:1129)
MAILBOX_UP = "Starting mailbox client for"
MAILBOX_MISSING = "Agent mailbox not found"
MAILBOX_FAILURES = ("Failed to connect to mailbox server", "Failed to retrieve messages", "Unable to publish manifest")
# uagents mailbox.py:155, logged by the module logger [mailbox], not by any agent: connect.py created the missing mailbox
MAILBOX_REGISTERED = "Successfully registered as mailbox agent"
SELLERS_JSON = REPO / "agents" / "sellers" / "sellers.json"
ORIGINS = ("LIVE", "MIRROR", "SIM")


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
    """Agents in one log: {tag: {address, last_message, last_index, mailbox}}; last_index orders messages across agents.
    mailbox is True only when that agent logged the mailbox client starting and none of the failure lines.
    An agent is a tag that logged "Starting agent with address:" (or a labelled address): every other tag in the log is a
    uagents module logger (resolver, dispenser, mailbox, network, setup, server, config ...) and never becomes a row.
    A [mailbox] "Successfully registered" line names no agent, so it clears the "mailbox not found" flag only when the
    waiting agent is the only one in the log that logged the mailbox client starting (any other running mailbox client
    could be the one connect.py registered); otherwise it cannot say which, and every agent stays as it is. When it does
    clear the flag, the stale 404 message is replaced by the registration line."""
    agents: dict[str, dict] = {}
    labels: dict[str, str] = {}  # address -> label ("seller_1 address: ...")
    lines = text.splitlines()
    real = {m.group(1) for m in (LINE_RE.match(r.strip()) for r in lines)
            if m and START_RE.search(m.group(2)) and not m.group(1).startswith("uagents") and m.group(1) != "bureau"}
    for i, raw in enumerate(lines):
        line = raw.strip()
        lab = LABEL_RE.match(line)
        if lab:
            labels[lab.group(2)] = lab.group(1)
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        tag, msg = m.group(1), m.group(2)
        if tag == "mailbox" and MAILBOX_REGISTERED in msg:
            waiting = [a for a in agents.values() if a["mailbox_missing"]]
            running = [a for a in agents.values() if a["mailbox_up"]]
            # connect.py can be run for any port, so another agent running a mailbox client may be the one registered:
            # only when the waiting agent is the single one that logged the mailbox client starting is it the one
            if len(waiting) == 1 and len(running) == 1 and running[0] is waiting[0]:
                a = waiting[0]
                a["mailbox_missing"] = False
                if a["last_message"] is not None and a["last_message"].startswith(MAILBOX_MISSING):
                    a["last_message"], a["last_index"] = clean(msg), i  # the 404 text is stale now
            continue
        if tag not in real:
            continue
        a = agents.setdefault(tag, {"address": None, "last_message": None, "last_index": -1, "mailbox_up": False,
                                    "mailbox_bad": False, "mailbox_missing": False})
        if MAILBOX_UP in msg:
            a["mailbox_up"] = True
        if MAILBOX_MISSING in msg:
            a["mailbox_missing"] = True
        if any(f in msg for f in MAILBOX_FAILURES):
            a["mailbox_bad"] = True
        s = START_RE.search(msg)
        if s:
            a["address"] = s.group(1)
        if any(n in msg for n in NOISE) or msg.startswith(RECORD_PREFIXES):
            continue
        a["last_message"] = clean(msg)
        a["last_index"] = i
    for addr, label in labels.items():  # an agent that only printed its labelled address still gets a row
        if not any(a["address"] == addr for a in agents.values()):
            agents.setdefault(label, {"address": addr, "last_message": None, "last_index": -1, "mailbox_up": False,
                                      "mailbox_bad": False, "mailbox_missing": False})
    for a in agents.values():
        a["mailbox"] = a.pop("mailbox_up") and not a.pop("mailbox_bad") and not a.pop("mailbox_missing")
    return agents


def last_line_index(text: str) -> int:
    """Index of the last non-blank line of any kind (noise, other agents, tracebacks included)."""
    last = -1
    for i, raw in enumerate(text.splitlines()):
        if raw.strip():
            last = i
    return last


def seller_origins(path: Path = SELLERS_JSON) -> dict[str, str]:
    """Seller display name -> origin from its sellers.json entry. Missing or odd config gives nothing, so rows fall back to SIM."""
    try:
        sellers = json.loads(path.read_text(encoding="utf-8")).get("sellers", {})
        return {v["name"]: v["origin"] for v in sellers.values()
                if isinstance(v, dict) and isinstance(v.get("name"), str) and v.get("origin") in ORIGINS}
    except (OSError, ValueError, AttributeError):
        return {}


def _mtime_iso(path: str) -> str | None:
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _row(name, role, address, status, message, at, origin="SIM") -> dict:
    return {"name": name, "role": role, "address": address, "status": status, "last_message": message, "at": at,
            "origin": origin if origin in ORIGINS else "SIM"}


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
    newest = max(agents, key=lambda t: agents[t]["last_index"])
    quiet_tail = agents[newest]["last_index"] == last_line_index(text)
    mtime = _mtime_iso(rec["log"])
    origins = seller_origins() if role == "seller" else {}
    rows = []
    for tag, a in agents.items():
        status = ("agentverse" if a["mailbox"] else "local") if alive else "down"
        stamped = mtime if (tag == newest and a["last_message"] is not None and quiet_tail) else None
        rows.append(_row(tag, role, a["address"], status, a["last_message"], stamped, origins.get(tag, "SIM")))
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


def create_app(run_dir: Path | str | None = None, memory_dir: Path | str | None = None):
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

    mem = Path(memory_dir or os.environ.get("MEMORY_DIR") or REPO / "demo" / "out")

    @app.get("/v1/memory")
    def memory(kind: str | None = None, limit: int | None = None, sample: bool = False) -> dict:
        from demo import memory as M
        return M.load(mem, include_sample=sample, kind=kind, limit=limit)

    return app


app = create_app()
