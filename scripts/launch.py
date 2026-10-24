#!/usr/bin/env python3
"""Tech Bazaar launcher: one command to bring the whole product up locally and say what is really up.

    python3 scripts/launch.py up        # preflight, then start every service that can start
    python3 scripts/launch.py status    # table: service, port, pid, health; exit 1 if a service is down
    python3 scripts/launch.py down      # stop only the processes this launcher started

Stdlib only (Python 3.12). Children run in their own process group, logs go to .run/logs/<service>.log, and the
pids live in .run/pids.json. Keys from --env-file go into child environments only; the launcher prints key NAMES
(present or missing), never values, and redacts known values from anything it echoes from a log.
Nothing global is ever installed: the only installs are a project-local `uv` venv for agents/ and `npm ci` in web/ and market/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = Path.home() / "hackathons" / "cal-hacks-13-2026" / "lane-d" / ".env"
HOST = "127.0.0.1"

SPACETIME_INSTALL = "curl -sSf https://install.spacetimedb.com | sh"
UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)"
NODE_INSTALL = "brew install node"
SHIELD_DEPS_FIX = "inside a venv: python3 -m pip install fastapi uvicorn"

# Names we report as present or missing. The list is read from .env.example at run time, this is the fallback.
FALLBACK_KEY_NAMES = ["ANTHROPIC_API_KEY", "AGENTVERSE_API_KEY", "STRIPE_SECRET_KEY", "APPROVAL_SECRET"]

ADDR_RE = re.compile(r"agent1q[0-9a-z]{40,70}")
# log markers worth surfacing in status: (substring, what it means)
LOG_WARNINGS = [("Unable to publish manifest", "Agentverse not reachable (manifest not published): the agent runs locally only")]
LABELLED_ADDR_RE = re.compile(r"^\s*(\w+) address: (agent1q[0-9a-z]{40,70})", re.M)


# ---------------------------------------------------------------- env file


def parse_env_text(text: str) -> tuple[dict[str, str], list[int]]:
    """Parse KEY=VALUE lines. Returns (values, bad_line_numbers). Never puts a value in an error."""
    values: dict[str, str] = {}
    bad: list[int] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, val = line.partition("=")
        key = key.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            bad.append(n)
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values, bad


def load_env_file(path: Path) -> tuple[dict[str, str], str]:
    """Return (non-empty values, one-line note with names only)."""
    if not path.is_file():
        return {}, f"env file not found: {path}"
    values, bad = parse_env_text(path.read_text(encoding="utf-8", errors="replace"))
    note = f"env file {path}: {len(values)} keys with a value"
    if bad:
        note += f", unparseable line numbers {bad}"
    return {k: v for k, v in values.items() if v != ""}, note


def key_names_from_example(example: Path) -> list[str]:
    if not example.is_file():
        return list(FALLBACK_KEY_NAMES)
    values, _ = parse_env_text(example.read_text(encoding="utf-8", errors="replace"))
    return list(values) or list(FALLBACK_KEY_NAMES)


def key_report(names: list[str], env: dict[str, str]) -> tuple[list[str], list[str]]:
    present = [n for n in names if env.get(n)]
    return present, [n for n in names if not env.get(n)]


def redact(text: str, secrets: dict[str, str]) -> str:
    """Replace every secret value (4+ chars) in text with ***."""
    for v in sorted((v for v in secrets.values() if len(v) >= 4), key=len, reverse=True):
        text = text.replace(v, "***")
    return text


# ---------------------------------------------------------------- services


@dataclass
class Service:
    name: str
    port: int | None
    cmd: list[str]
    cwd: Path
    health: str = "http"  # "http" or "tcp"
    health_path: str = "/"
    wait: float = 30.0
    env_filter: str = "all"  # "all" or "web" (only NEXT_PUBLIC_* and SPACETIMEDB_*)
    extra_env: dict[str, str] = field(default_factory=dict)  # always applied, wins over the env file
    defaults: dict[str, str] = field(default_factory=dict)  # applied only when neither environment nor env file set the name
    note: str = ""
    skip_reason: str | None = None
    group: str = ""


def env_for(svc: Service, file_env: dict[str, str]) -> dict[str, str]:
    env = dict(svc.defaults)
    env.update(os.environ)
    if svc.env_filter == "web":
        env.update({k: v for k, v in file_env.items() if k.startswith(("NEXT_PUBLIC_", "SPACETIMEDB"))})
    else:
        env.update(file_env)
    env.update(svc.extra_env)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def venv_python(repo: Path) -> Path:
    return repo / "agents" / ".venv" / "bin" / "python"


def find_uv() -> str | None:
    return find_tool("uv")


def find_tool(name: str, which=shutil.which, home_bin: Path | None = None) -> str | None:
    """PATH first, then ~/.local/bin (where uv and spacetime install themselves, often not on a non-login PATH)."""
    found = which(name)
    if found:
        return found
    p = (home_bin if home_bin is not None else Path.home() / ".local" / "bin") / name
    return str(p) if p.is_file() else None


MAILBOX_FLAGS = {"buyer": "BUYER_MAILBOX", "advocate": "ADVOCATE_MAILBOX", "sellers": "SELLERS_MAILBOX"}


def mailbox_record(svc: Service, file_env: dict[str, str] | None = None, agents_env: dict[str, str] | None = None) -> bool:
    """True when this agent service starts in Agentverse mailbox mode, computed the way agents/common.py mailbox_on does
    (AGENTS_MAILBOX or its own flag) over the final env: `up --mailbox`, the environment and the launcher env file win, then
    agents/.env, which the agents load themselves without overriding. The pidfile records it as a hint; the agent feed decides
    what to show from the agents' own log lines."""
    flag = MAILBOX_FLAGS.get(svc.name)
    if flag is None:
        return False
    env = {**(agents_env or {}), **env_for(svc, file_env or {})}
    return bool(env.get("AGENTS_MAILBOX") or env.get(flag))


def build_services(a, repo: Path = REPO) -> list[Service]:
    shield_url = f"http://{HOST}:{a.shield_port}"
    py = str(venv_python(repo))
    mb = getattr(a, "mailbox", False)
    agent_env = lambda flag: {"SHIELD_URL": shield_url, **({flag: "1"} if mb else {})}  # noqa: E731
    mode = "Agentverse mailbox" if mb else "local mode, not Agentverse mailbox"
    return [
        Service("market-stdb", a.stdb_port, [find_tool("spacetime") or "spacetime", "start", "--listen-addr", f"{HOST}:{a.stdb_port}"], repo / "market",
                health_path="/v1/ping", wait=40, group="market",
                note="SpacetimeDB; tech-bazaar module published and seed_demo run by `up`"),
        Service("shield", a.shield_port,
                [sys.executable, "-m", "uvicorn", "shield.api:app", "--host", HOST, "--port", str(a.shield_port)], repo,
                health_path="/v1/shield/health", wait=30, group="shield"),
        Service("sellers", 8010, [py, "sellers/run_all.py"], repo / "agents", health="tcp", wait=90, group="agents",
                extra_env=agent_env("SELLERS_MAILBOX"), note=f"3 seller agents in one Bureau, {mode} (port fixed in code)"),
        Service("advocate", 8003, [py, "-m", "advocate.advocate_agent"], repo / "agents", health="tcp", wait=90,
                group="agents", extra_env=agent_env("ADVOCATE_MAILBOX"), note=f"{mode}; port fixed in code"),
        Service("buyer", 8001, [py, "buyer/buyer_agent.py"], repo / "agents", health="tcp", wait=90, group="agents",
                extra_env=agent_env("BUYER_MAILBOX"), note=f"{mode}; port fixed in code"),
        Service("agent-feed", 8790,
                [sys.executable, "-m", "uvicorn", "agent_feed:app", "--app-dir", str(repo / "scripts"), "--host", HOST, "--port", "8790"],
                repo, health_path="/v1/health", wait=30, group="feed",
                extra_env={"AGENT_FEED_RUN_DIR": str(Path(getattr(a, "run_dir", None) or repo / ".run").resolve())},
                note="read-only feed of the agents' status and last lines for the web corner tile"),
        Service("seller-kit", 8791,
                [sys.executable, "-m", "uvicorn", "seller_kit.api:app", "--host", HOST, "--port", "8791"],
                repo, health_path="/v1/health", wait=30, group="kit",
                note="Seller Kit API: checks a shop's config and writes it to agents/sellers/custom/ for the /sell page; starts no agent"),
        Service("web", a.web_port,
                ["npm", "exec", "--no-install", "--", "next", "dev", "-p", str(a.web_port)], repo / "web", wait=150, env_filter="web",
                group="web", extra_env={"NEXT_TELEMETRY_DISABLED": "1"},
                defaults={"NEXT_PUBLIC_SPACETIMEDB_URI": f"ws://{HOST}:{a.stdb_port}",
                                        "NEXT_PUBLIC_SPACETIMEDB_DB": "tech-bazaar"}),
    ]


# ---------------------------------------------------------------- preflight


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    auto: str = ""  # non-empty: `up` fixes this itself, with this note


def run_preflight(a, services: list[Service], file_env: dict[str, str], env_note: str, *,
                  repo: Path = REPO, which=shutil.which, can_import=None, port_busy=None,
                  owned_ports: set[int] | None = None, home_bin: Path | None = None) -> list[Check]:
    can_import = can_import or (lambda mod: __import__("importlib.util").util.find_spec(mod) is not None)
    port_busy = port_busy or tcp_open
    owned_ports = owned_ports or set()
    out: list[Check] = []
    v = sys.version_info
    out.append(Check("python 3.12+", v >= (3, 12), f"{v.major}.{v.minor}.{v.micro}", "install Python 3.12 from python.org"))
    deps = all(can_import(m) for m in ("fastapi", "uvicorn"))
    out.append(Check("shield deps (fastapi, uvicorn)", deps, "", SHIELD_DEPS_FIX))
    uv = find_uv()
    out.append(Check("uv", bool(uv), uv or "", UV_INSTALL))
    venv_ok = venv_python(repo).exists()
    out.append(Check("agents/.venv", venv_ok, "", "", auto="up creates it with uv and installs agents/requirements.txt"))
    node = which("node")
    out.append(Check("node", bool(node), node or "", NODE_INSTALL))
    out.append(Check("npm", bool(which("npm")), "", NODE_INSTALL))
    out.append(Check("web/node_modules", (repo / "web" / "node_modules").is_dir(), "", "",
                     auto="up runs `npm ci` in web/"))
    stdb = find_tool("spacetime", which, home_bin)
    out.append(Check("spacetime CLI", bool(stdb), stdb or "", SPACETIME_INSTALL))
    if stdb:
        out.append(Check("market/node_modules", (repo / "market" / "node_modules").is_dir(), "", "",
                         auto="up runs `npm ci` in market/"))
    env_ok = bool(file_env)
    out.append(Check("env file", env_ok, env_note.removeprefix("env file "), f"create it from .env.example, or pass --env-file PATH"))
    names = key_names_from_example(repo / ".env.example")
    present, missing = key_report(names, file_env)
    out.append(Check("keys present (names only)", bool(present), ", ".join(present) or "none"))
    if missing:
        out.append(Check("keys missing (names only)", False, ", ".join(missing),
                         "only needed for the features that use them; nothing is blocked by this list alone"))
    for s in services:
        if s.port is None:
            continue
        busy = port_busy(s.port) and s.port not in owned_ports
        out.append(Check(f"port {s.port} free ({s.name})", not busy, "", f"stop what is using it, or pass a different port flag"
                         if s.name in ("shield", "web", "market-stdb") else "stop what is using it (this port is fixed in agents/ code)"))
    return out


def print_preflight(checks: list[Check], out=sys.stdout) -> None:
    for c in checks:
        tag = "OK" if c.ok else "MISSING"
        line = f"  [{tag:<7}] {c.name}"
        if c.detail:
            line += f": {c.detail}"
        if not c.ok:
            if c.auto:
                line += f"  -> {c.auto}"
            elif c.fix:
                line += f"  -> fix: {c.fix}"
        print(line, file=out)


def decide_skips(services: list[Service], checks: list[Check]) -> None:
    """Set skip_reason on services whose hard prerequisites are MISSING (and not auto-fixable)."""
    bad = {c.name: c for c in checks if not c.ok and not c.auto}
    for s in services:
        if s.skip_reason:
            continue
        if s.name == "market-stdb" and "spacetime CLI" in bad:
            s.skip_reason = f"spacetime CLI not installed. Install: {SPACETIME_INSTALL}"
        elif s.name in ("shield", "agent-feed", "seller-kit") and "shield deps (fastapi, uvicorn)" in bad:
            s.skip_reason = f"fastapi/uvicorn not importable. Fix: {SHIELD_DEPS_FIX}"
        elif s.group == "agents" and "uv" in bad and "agents/.venv" in {c.name for c in checks if not c.ok}:
            s.skip_reason = f"uv not found and agents/.venv missing. Install: {UV_INSTALL}"
        elif s.name == "web" and ("node" in bad or "npm" in bad):
            s.skip_reason = f"node/npm not found. Install: {NODE_INSTALL}"


# ---------------------------------------------------------------- processes and pidfile


def tcp_open(port: int, host: str = HOST, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(port: int, path: str, timeout: float = 2.0, max_status: int = 500) -> bool:
    """Any HTTP response below max_status means a live server; a refused connection or a 5xx does not."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}{path}", timeout=timeout) as r:
            return r.status < max_status
    except urllib.error.HTTPError as e:
        return e.code < max_status
    except Exception:
        return False


def proc_start_marker(pid: int) -> str | None:
    """`ps lstart` of the pid, used to tell our process from a reused pid. None when the pid is gone."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                           env={**os.environ, "LC_ALL": "C"}, timeout=5)
    except Exception:
        return None
    s = r.stdout.strip()
    return s if r.returncode == 0 and s else None


def pid_is_ours(rec: dict) -> bool:
    pid = rec.get("pid")
    return bool(pid) and rec.get("lstart") is not None and proc_start_marker(pid) == rec.get("lstart")


class PidFile:
    def __init__(self, run_dir: Path):
        self.path = run_dir / "pids.json"

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def log_path(run_dir: Path, name: str) -> Path:
    return run_dir / "logs" / f"{name}.log"


def start_process(svc: Service, env: dict[str, str], run_dir: Path) -> dict:
    """Start svc detached in its own process group. Returns its pidfile record."""
    lp = log_path(run_dir, svc.name)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "wb") as lf:
        p = subprocess.Popen(svc.cmd, cwd=svc.cwd, env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                             start_new_session=True)
    return {"state": "running", "pid": p.pid, "lstart": proc_start_marker(p.pid), "port": svc.port,
            "health": svc.health, "health_path": svc.health_path, "log": str(lp), "note": svc.note, "group": svc.group}


def stop_record(rec: dict, grace: float = 6.0) -> str:
    """Stop the process group of a record, only if the pid is still the process we started."""
    pid = rec.get("pid")
    if not pid:
        return "nothing to stop"
    if not pid_is_ours(rec):
        return f"pid {pid} is gone (or reused by something else), left alone"
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return f"pid {pid} already gone"
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_is_ours(rec):
            return f"stopped pid {pid}"
        time.sleep(0.15)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return f"killed pid {pid} (did not exit in {grace:.0f}s)"


# ---------------------------------------------------------------- status


def addresses_from_log(path: str | None, service: str) -> list[str]:
    """Agentverse addresses a service printed, as 'label: address'."""
    if not path:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = {addr: label for label, addr in LABELLED_ADDR_RE.findall(text)}
    for addr in ADDR_RE.findall(text):
        found.setdefault(addr, service)
    return [f"{label}: {addr}" for addr, label in found.items()]


def log_warnings(path: str | None) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace") if path else ""
    except OSError:
        return []
    return [msg for needle, msg in LOG_WARNINGS if needle in text]


def evaluate(rec: dict, check_http=http_ok, check_tcp=tcp_open) -> tuple[str, str]:
    """Return (label, health text). Labels: UP, DOWN, SKIPPED, FAILED."""
    state = rec.get("state")
    if state == "skipped":
        return "SKIPPED", rec.get("reason", "")
    if state == "failed":
        return "FAILED", rec.get("reason", "")
    if not pid_is_ours(rec):
        return "DOWN", "process is not running (see log)"
    port = rec.get("port")
    if port is None:
        return "UP", "process alive"
    if rec.get("health") == "http":
        path = rec.get("health_path", "/")
        ok = check_http(port, path)
        return ("UP", f"http GET {path} ok") if ok else ("DOWN", f"pid alive but http GET {path} on {port} gets no answer")
    ok = check_tcp(port)
    return ("UP", "tcp connect ok") if ok else ("DOWN", f"pid alive but nothing listens on {port}")


def status_rows(state: dict, **kw) -> list[dict]:
    rows = []
    for name, rec in state.get("services", {}).items():
        label, health = evaluate(rec, **kw)
        rows.append({"service": name, "port": rec.get("port"), "pid": rec.get("pid") if label in ("UP", "DOWN") else None,
                     "label": label, "health": health, "note": rec.get("note", ""), "log": rec.get("log"),
                     "addresses": addresses_from_log(rec.get("log"), name) if label in ("UP", "DOWN") else [],
                     "warnings": (log_warnings(rec.get("log")) + rec.get("static_warnings", [])) if label == "UP" else []})
    return rows


def format_table(rows: list[dict]) -> str:
    heads = ["service", "port", "pid", "status", "health"]
    data = [[r["service"], str(r["port"] or "-"), str(r["pid"] or "-"), r["label"], r["health"]] for r in rows]
    widths = [max(len(h), *(len(d[i]) for d in data)) if data else len(h) for i, h in enumerate(heads)]
    # the last column is free text, do not pad it
    lines = ["  ".join(h.ljust(widths[i]) if i < 4 else h for i, h in enumerate(heads))]
    lines.append("  ".join("-" * widths[i] if i < 4 else "-" * len(heads[i]) for i in range(5)))
    for d in data:
        lines.append("  ".join(d[i].ljust(widths[i]) if i < 4 else d[i] for i in range(5)))
    out = "\n".join(lines)
    addr = [(r["service"], x) for r in rows for x in r["addresses"]]
    if addr:
        out += "\n\nAgentverse addresses printed by the agents (from their logs):\n" + "\n".join(f"  {s:<9} {x}" for s, x in addr)
    notes = [f"  {r['service']}: {r['note']}" for r in rows if r["note"] and r["label"] in ("UP", "DOWN")]
    notes += [f"  {r['service']}: WARNING {w}" for r in rows for w in r.get("warnings", [])]
    if notes:
        out += "\n\nNotes:\n" + "\n".join(notes)
    return out


def exit_code(rows: list[dict], strict: bool = False) -> int:
    if not rows:
        return 1
    bad = {"DOWN", "FAILED"} | ({"SKIPPED"} if strict else set())
    return 1 if any(r["label"] in bad for r in rows) else 0


def web_note(rows_state: dict) -> None:
    """Be honest that the web screens have no live data when the market is not running."""
    sv = rows_state.get("services", {})
    if "web" in sv and sv["web"].get("state") == "running" and sv.get("market-stdb", {}).get("state") != "running":
        sv["web"]["note"] = "market is not running: the screens load but show no live data (the SpacetimeDB socket will not connect)"


def cmd_status(run_dir: Path, strict: bool = False, out=sys.stdout, **kw) -> int:
    state = PidFile(run_dir).load()
    if not state.get("services"):
        print("Nothing started by this launcher (no .run/pids.json). Run: python3 scripts/launch.py up", file=out)
        return 1
    web_note(state)
    rows = status_rows(state, **kw)
    print(format_table(rows), file=out)
    skipped = [r["service"] for r in rows if r["label"] == "SKIPPED"]
    code = exit_code(rows, strict)
    up = sum(r["label"] == "UP" for r in rows)
    print(f"\n{up}/{len(rows)} up, {len(skipped)} skipped" + (f" ({', '.join(skipped)})" if skipped else "")
          + f", exit {code}", file=out)
    return code


# ---------------------------------------------------------------- up / down


def tail(path: Path, n: int = 4, secrets: dict[str, str] | None = None) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return "(no log)"
    return redact("\n      ".join(l[:200] for l in lines), secrets or {})


def run_step(label: str, cmd: list[str], cwd: Path, env: dict[str, str], run_dir: Path, logname: str, timeout: int = 900) -> bool:
    lp = log_path(run_dir, logname)
    lp.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ... {label}  (log: {lp})", flush=True)
    try:
        with open(lp, "wb") as lf:
            r = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_agents_venv(repo: Path, run_dir: Path, env: dict[str, str]) -> str | None:
    """Create agents/.venv with uv and install requirements. Returns an error string or None."""
    py = venv_python(repo)
    uv = find_uv()
    if not py.exists():
        if not uv:
            return f"uv not found. Install: {UV_INSTALL}"
        if not run_step("uv venv agents/.venv", [uv, "venv", "--python", "3.12", "--no-python-downloads", str(repo / "agents" / ".venv")],
                        repo, env, run_dir, "setup-agents-venv"):
            return f"uv venv failed, see {log_path(run_dir, 'setup-agents-venv')}"
    probe = subprocess.run([str(py), "-c", "import uagents, jsonschema"], capture_output=True)
    if probe.returncode != 0:
        if not uv:
            return f"agents/.venv lacks uagents and uv is missing. Install: {UV_INSTALL}"
        if not run_step("uv pip install -r agents/requirements.txt", [uv, "pip", "install", "--python", str(py), "-r",
                                                                       str(repo / "agents" / "requirements.txt")],
                        repo, env, run_dir, "setup-agents-install"):
            return f"uv pip install failed, see {log_path(run_dir, 'setup-agents-install')}"
    return None


def ensure_npm(repo: Path, folder: str, run_dir: Path, env: dict[str, str]) -> str | None:
    d = repo / folder
    if (d / "node_modules").is_dir():
        return None
    if not run_step(f"npm ci in {folder}/", ["npm", "ci", "--no-audit", "--no-fund"], d, env, run_dir, f"setup-{folder}-npm"):
        return f"npm ci in {folder}/ failed, see {log_path(run_dir, f'setup-{folder}-npm')}"
    return None


def wait_ready(svc: Service, rec: dict, deadline: float) -> tuple[bool, str]:
    while time.time() < deadline:
        if not pid_is_ours(rec):
            return False, "process exited during startup"
        label, _ = evaluate(rec)
        if label == "UP":
            return True, ""
        time.sleep(0.5)
    return False, f"no health answer after {svc.wait:.0f}s"


def carry_live(state: dict, live: dict) -> dict:
    """Keep records of running services that this `up` did not select (`--only`), so `down` still stops them."""
    for n, r in live.items():
        state["services"].setdefault(n, r)
    return state


def cmd_up(a, repo: Path = REPO) -> int:
    run_dir = Path(a.run_dir).resolve()
    pf = PidFile(run_dir)
    services = build_services(a, repo)
    if a.only:
        wanted = {x.strip() for x in a.only.split(",")}
        services = [s for s in services if s.name in wanted or s.group in wanted]

    old = pf.load().get("services", {})
    live = {n: r for n, r in old.items() if r.get("state") == "running" and pid_is_ours(r)}
    file_env, env_note = load_env_file(Path(a.env_file).expanduser())
    secrets = dict(file_env)

    print(f"Tech Bazaar launcher, repo {repo}\n\nPreflight:")
    owned = {r["port"] for r in live.values() if r.get("port")}
    checks = run_preflight(a, services, file_env, env_note, repo=repo, owned_ports=owned)
    print_preflight(checks)
    decide_skips(services, checks)

    state: dict = carry_live({"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "services": {}}, live)
    run_env = dict(os.environ)
    if shutil.which("node"):
        run_env["PATH"] = str(Path(shutil.which("node")).parent) + os.pathsep + run_env.get("PATH", "")
    run_env["PATH"] = run_env["PATH"] + os.pathsep + str(Path.home() / ".local" / "bin") if "PATH" in run_env else str(Path.home() / ".local" / "bin")

    def record(svc: Service, rec: dict) -> None:
        rec.setdefault("note", svc.note)
        state["services"][svc.name] = rec
        pf.save(state)

    def skip(svc: Service, reason: str, kind: str = "skipped") -> None:
        print(f"  {kind.upper():<8} {svc.name}: {reason}")
        record(svc, {"state": kind, "port": svc.port, "reason": reason})

    print("\nStarting:")
    # keep services that are already running under this launcher
    for svc in list(services):
        if svc.name in live:
            print(f"  already running: {svc.name} (pid {live[svc.name]['pid']})")
            record(svc, live[svc.name])
            services.remove(svc)

    # setup that must happen before a service can start
    agents_err = None
    if any(s.group == "agents" and not s.skip_reason for s in services):
        agents_err = ensure_agents_venv(repo, run_dir, run_env)
    web_err = ensure_npm(repo, "web", run_dir, run_env) if any(s.name == "web" and not s.skip_reason for s in services) else None
    stdb_ready = False
    if not agents_err and venv_python(repo).exists() and "SSL_CERT_FILE" not in os.environ:
        # macOS python has no CA bundle of its own; point the agents at certifi from their own venv (nothing installed)
        r = subprocess.run([str(venv_python(repo)), "-c", "import certifi;print(certifi.where())"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            for s_ in services:
                if s_.group == "agents":
                    s_.defaults["SSL_CERT_FILE"] = r.stdout.strip()

    started: list[tuple[Service, dict]] = []
    agents_env = load_env_file(repo / "agents" / ".env")[0]

    def launch(svc: Service) -> dict | None:
        if svc.skip_reason:
            skip(svc, svc.skip_reason)
            return None
        if svc.port is not None and tcp_open(svc.port):
            skip(svc, f"port {svc.port} is already in use by a process this launcher did not start", "failed")
            return None
        rec = start_process(svc, env_for(svc, file_env), run_dir)
        rec["mailbox"] = mailbox_record(svc, file_env, agents_env)
        record(svc, rec)
        print(f"  started  {svc.name} pid {rec['pid']} (log {rec['log']})")
        started.append((svc, rec))
        return rec

    # market first: the module is published and seeded once SpacetimeDB answers
    for svc in [s for s in services if s.name == "market-stdb"]:
        npm_err = None if svc.skip_reason else ensure_npm(repo, "market", run_dir, run_env)
        if npm_err:
            skip(svc, npm_err, "failed")
            continue
        rec = launch(svc)
        if rec:
            ok, why = wait_ready(svc, rec, time.time() + svc.wait)
            if not ok:
                state["services"][svc.name] = {**rec, "reason": why}
                pf.save(state)
                print(f"  NOT READY {svc.name}: {why}")
            else:
                stdb_ready = True
                server = f"http://{HOST}:{a.stdb_port}"
                senv = {**env_for(svc, file_env), "SPACETIMEDB_HTTP": server, "SPACETIMEDB_SERVER": server}
                steps = [("spacetime publish tech-bazaar", [svc.cmd[0], "publish", "-s", server, "-p", "./spacetimedb", "--yes=all", "tech-bazaar"],
                          repo / "market", "setup-market-publish", 300),
                         ("spacetime call seed_demo", [svc.cmd[0], "call", "-s", server, "tech-bazaar", "seed_demo"],
                          repo / "market", "setup-market-seed", 120),
                         ("market/scripts/setup_roles.py", [sys.executable, str(repo / "market" / "scripts" / "setup_roles.py")],
                          repo, "setup-market-roles", 120)]
                warns = []
                for label, cmd, cwd, logname, to in steps:
                    if not run_step(label, cmd, cwd, senv, run_dir, logname, to):
                        warns.append(f"setup step failed: {label} (log {log_path(run_dir, logname)})")
                if not http_ok(a.stdb_port, "/v1/database/tech-bazaar", max_status=300):
                    warns.append("module tech-bazaar is not published (the market has no tables)")
                if warns:
                    rec["static_warnings"] = warns
                    pf.save(state)

    for svc in [s for s in services if s.name != "market-stdb"]:
        if svc.group == "agents" and agents_err and not svc.skip_reason:
            skip(svc, agents_err, "failed")
        elif svc.name == "web" and web_err and not svc.skip_reason:
            skip(svc, web_err, "failed")
        else:
            launch(svc)

    # wait for everything started in this run, concurrently
    print("\nWaiting for health:")
    pending = {svc.name: (svc, rec, time.time() + svc.wait) for svc, rec in started if svc.name != "market-stdb"}
    while pending:
        for name in list(pending):
            svc, rec, deadline = pending[name]
            label, _ = evaluate(rec)
            if label == "UP":
                print(f"  UP       {name}")
                del pending[name]
            elif not pid_is_ours(rec):
                print(f"  EXITED   {name}: last log lines:\n      {tail(Path(rec['log']), secrets=secrets)}")
                del pending[name]
            elif time.time() > deadline:
                print(f"  TIMEOUT  {name}: no health answer after {svc.wait:.0f}s (still running; see {rec['log']})")
                del pending[name]
        if pending:
            time.sleep(0.5)

    print("\nStatus:\n")
    return cmd_status(run_dir, strict=False)


def cmd_down(a) -> int:
    run_dir = Path(a.run_dir).resolve()
    pf = PidFile(run_dir)
    state = pf.load()
    if not state.get("services"):
        print("Nothing to stop (no .run/pids.json).")
        return 0
    for name, rec in reversed(list(state["services"].items())):
        if rec.get("state") in ("skipped", "failed") and not rec.get("pid"):
            continue
        print(f"  {name}: {stop_record(rec)}")
    pf.clear()
    return 0


# ---------------------------------------------------------------- cli


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="launch.py", description="Bring Tech Bazaar up locally and say what is really up.",
                                epilog="The agent ports (sellers 8010, advocate 8003, buyer 8001) are fixed in agents/ code and have no flag.")
    p.add_argument("command", choices=["up", "status", "down"])
    p.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="KEY=VALUE file loaded into child environments only (default: %(default)s)")
    p.add_argument("--run-dir", default=str(REPO / ".run"), help="pidfile and logs directory (default: %(default)s)")
    p.add_argument("--shield-port", type=int, default=8787)
    p.add_argument("--web-port", type=int, default=3100)
    p.add_argument("--stdb-port", type=int, default=3000, help="SpacetimeDB listen port")
    p.add_argument("--only", help="comma list of service or group names to start (market-stdb, shield, agents, sellers, advocate, buyer, agent-feed, seller-kit, web)")
    p.add_argument("--mailbox", action="store_true",
                   help="up: start the agents in Agentverse mailbox mode (BUYER_MAILBOX, ADVOCATE_MAILBOX, SELLERS_MAILBOX); register each once with agents/connect.py <port>")
    p.add_argument("--strict", action="store_true", help="status: also exit 1 when a service is SKIPPED")
    return p


def main(argv: list[str] | None = None) -> int:
    a = make_parser().parse_args(argv)
    if a.command == "up":
        return cmd_up(a)
    if a.command == "status":
        return cmd_status(Path(a.run_dir).resolve(), strict=a.strict)
    return cmd_down(a)


if __name__ == "__main__":
    sys.exit(main())
