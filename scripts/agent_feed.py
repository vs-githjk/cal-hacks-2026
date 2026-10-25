"""Agent feed: what the Fetch agents are doing, read from the launcher's own run dir (pids.json and .run/logs).

GET /v1/agents -> [{name, role, address, status, last_message, at, origin}]
GET /v1/build -> the latest BuildView demo/build.py wrote (build-view.json in its out dir, BUILD_VIEW_DIR overrides), for the /buyer
build panel (web/src/lib/buildView.ts): 404 until a run wrote one, 503 when the file is half written or not a BuildView.
Local and operator-only like the rest of this feed (127.0.0.1, CORS for localhost pages only). It is NOT the public copy that goes to the
hosted board (build.public_view): it keeps the buyer's own budget, spent and approval totals because the panel parses them, and
buyer_view() strips everything else private (mandates, hashes, payees, per-mandate amounts, approval method and reason, the call,
approval and receipt events and any key it does not know). Two sponsor proof lines are served on purpose, each cut down to what carries no
money: a champion's liveCheck keeps only {state, origin, source, fetchedAt} (the time only for a LIVE read; never the price read or the quote),
and a part's Tiger Data history keeps only {state, origin, windows [{days, low, median, n, daysOfData}]} (market prices of its SKU).
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
BUILD_VIEW_FILE = "build-view.json"   # the name demo.build.VIEW_FILE writes (tested equal); the path comes from demo.build.OUT_DIR
MAX_BUILD_VIEW_BYTES = 2_000_000
BUILD_EVENT_KINDS = ("plan", "round_open", "knockout", "locked", "clash", "replan")  # no call, approved, denied or receipt lines


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


def default_build_dir() -> Path:
    """The folder demo/build.py writes build-view.json to by default (its own OUT_DIR, not a copy of the path)."""
    from demo.build import OUT_DIR
    return OUT_DIR


def _pick(d: dict, keys: tuple) -> dict:
    return {k: d[k] for k in keys if k in d}


def _rows(v: object) -> list[dict]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


LIVE_CHECK_STATES = ("ok", "price_changed", "out_of_stock", "stock_unknown", "slow", "empty", "not_configured", "skipped")
HISTORY_STATES = ("ok", "no_data", "not_configured", "error")


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _live_check(lc: dict) -> dict | None:
    """The part of the Bright Data re-check the buyer's panel may show: whether it read a price, when, and from where. Never the price it
    read or the quote it compared with. `fetchedAt` goes out only with a LIVE label, and a LIVE label only with a real time: anything
    else was not read in this run, so it is MIRROR and carries no time."""
    state = lc.get("state")
    if state not in LIVE_CHECK_STATES:
        return None
    at = lc.get("fetchedAt")
    live = lc.get("origin") == "LIVE" and isinstance(at, str) and bool(at) and len(at) <= 40
    out = {"state": state, "origin": "LIVE" if live else "MIRROR", "source": "Bright Data"}
    if live:
        out["fetchedAt"] = at
    return out


def _history(h: object) -> dict | None:
    """Tiger Data's 7 and 30 day read for one part: market prices of its SKU (low, median, rows, days held), no buyer money. A stored
    read is dated, so it is never labelled LIVE here; a window that is not the shape is dropped, never repaired."""
    if not isinstance(h, dict) or h.get("state") not in HISTORY_STATES:
        return None
    windows = [{k: w[k] for k in ("days", "low", "median", "n", "daysOfData")} for w in _rows(h.get("windows"))
               if all(_num(w.get(k)) for k in ("days", "low", "median", "n", "daysOfData")) and w["low"] > 0 and w["median"] > 0]
    return {"state": h["state"], "origin": h["origin"] if h.get("origin") in ("MIRROR", "SIM") else "MIRROR" if h.get("origin") == "LIVE" else "SIM",
            "windows": windows}


def buyer_view(v: dict) -> dict:
    """The BuildView for the buyer's own panel, rebuilt from an allow-list of keys so nothing unknown or private can ride along.
    Raises ValueError when v is not a BuildView (no goal id, or parts, checks or events that are not lists)."""
    if not isinstance(v, dict) or not isinstance(v.get("goalId"), str) or not v["goalId"] or any(
            not isinstance(v.get(k), list) for k in ("parts", "checks", "events")):
        raise ValueError("not a BuildView")
    parts = []
    for p in _rows(v["parts"]):
        q = _pick(p, ("part", "label", "status", "origin", "budget", "needId", "roundId", "reason"))
        if isinstance(p.get("champion"), dict):
            q["champion"] = _pick(p["champion"], ("bidId", "sellerId", "persona", "landed", "origin", "sourceUrl"))
            lc = _live_check(p["champion"]["liveCheck"]) if isinstance(p["champion"].get("liveCheck"), dict) else None
            if lc is not None:
                q["champion"]["liveCheck"] = lc
            hist = _history(p.get("history"))
            if hist is not None:
                q["history"] = hist
        parts.append(q)
    approval = v.get("approval") if isinstance(v.get("approval"), dict) else None
    return {**_pick(v, ("goalId", "buyerId", "budget", "spent", "origin")), "parts": parts,
            "checks": [_pick(c, ("a", "b", "rule", "state", "detail", "source")) for c in _rows(v["checks"])],
            "events": [_pick(e, ("at", "kind", "text", "parts", "origin")) for e in _rows(v["events"]) if e.get("kind") in BUILD_EVENT_KINDS],
            "approval": _pick(approval, ("state", "total", "sellers")) if approval is not None else None}


def read_build_view(build_dir: Path) -> dict | None:
    """The served view, None when no run wrote one yet. Raises ValueError for a file that is unreadable, too big or not a BuildView."""
    path = build_dir / BUILD_VIEW_FILE
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BUILD_VIEW_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValueError(f"cannot read {BUILD_VIEW_FILE}: {type(e).__name__}") from e
    if len(raw) > MAX_BUILD_VIEW_BYTES:
        raise ValueError(f"{BUILD_VIEW_FILE} is over {MAX_BUILD_VIEW_BYTES} bytes")
    try:
        view = buyer_view(json.loads(raw.decode("utf-8")))
        json.dumps(view, ensure_ascii=False).encode("utf-8")  # a lone surrogate would break the response, so refuse it here
    except (ValueError, RecursionError) as e:  # JSONDecodeError and UnicodeError are ValueErrors
        raise ValueError(f"{BUILD_VIEW_FILE} is not a readable BuildView") from e
    return view


def create_app(run_dir: Path | str | None = None, memory_dir: Path | str | None = None, build_dir: Path | str | None = None):
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

    built = Path(build_dir or os.environ.get("BUILD_VIEW_DIR") or default_build_dir())

    @app.get("/v1/build")
    def build():
        from fastapi.responses import JSONResponse
        try:
            view = read_build_view(built)
        except ValueError as e:  # a half-written or odd file is a transient, never a 500; the panel keeps its SIM sample meanwhile
            return JSONResponse({"detail": str(e)}, status_code=503)
        if view is None:
            return JSONResponse({"detail": "no build run has written a view yet"}, status_code=404)
        return JSONResponse(view, headers={"Cache-Control": "no-store"})

    return app


app = create_app()
