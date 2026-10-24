#!/usr/bin/env python3
"""Rehearsal harness: run the five-beat skeleton N times against the local stack and record what happened.

    python3 demo/rehearse.py --runs 3 --screens --out demo/rehearsal/2026-10-24-night2
    python3 demo/rehearse.py --runs 1 --dry-run        # print the plan, touch nothing

For every run it records the wall time, seconds per beat (from the `BEAT <n>` lines the stage command prints), the exit code,
read-only end-state checks against the local SpacetimeDB, and optional headless Chrome screenshots of /buyer and /market at
the end of each beat. It writes `<out>/REPORT.md`, `<out>/runs.json` and one `<out>/run<k>.log` per run.

Nothing is faked: a check that cannot be read is recorded as `skipped` with the reason, a screenshot that fails is recorded
and never fatal, and a stack that is down means no run (exit code 2). Secrets: the harness reads no token or env file, and
any env value whose name looks secret is replaced by `[redacted]` in everything it prints or writes.

Exit codes: 0 every run exited 0 and no check failed, 1 a run failed or a check failed, 2 the stack is down.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]

STDB_PORT = 3000           # SpacetimeDB (scripts/launch.py default)
WEB_PORT = 3100            # web app (scripts/launch.py default)
HOST = "127.0.0.1"
TARGET_SECONDS = 120       # the 2:00 cut
BEATS = ("1", "2", "3", "4", "5")
PAGES = ("buyer", "market")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DSN|DATABASE_URL|SERVICE_URL", re.I)
BEAT_LINE = re.compile(r"^\s*BEAT\s+([1-5])\b")

# Read-only, fixed queries. Each check passes when its predicate holds on the rows the CLI returned.
CHECKS = {
    "round_closed": ("SELECT id, state FROM round",
                     lambda rows: bool(rows) and all(str(r[-1]).strip('"') == "closed" for r in rows),
                     "every round has state closed"),
    "awarded_line": ("SELECT round_id, rank FROM round_result WHERE rank = 1",
                     lambda rows: len(rows) >= 1, "a bid holds rank 1 in round_result"),
    "payment_row": ("SELECT mode FROM payment",
                    lambda rows: len(rows) >= 1, "the payment table has a row"),
    "round_2_present": ("SELECT id FROM round",
                        lambda rows: len(rows) >= 2, "at least two rounds exist"),
}


# ---------------------------------------------------------------- pure helpers

def parse_beat(line: str) -> Optional[int]:
    m = BEAT_LINE.match(line)
    return int(m.group(1)) if m else None


def default_stage_cmd(root: Path = ROOT) -> str:
    stage = Path(root) / "demo" / "stage.py"
    if stage.exists():
        return f"python3 {stage} --auto"
    return f"python3 {Path(root) / 'demo' / 'bridge.py'} --reset --rounds 2 --step-delay 1"


def secret_values(env: dict) -> list:
    vals = {v for k, v in env.items() if SECRET_NAME.search(k) and len(v) >= 6}
    return sorted(vals, key=len, reverse=True)


def redact(text: str, secrets: list) -> str:
    for v in secrets:
        text = text.replace(v, "[redacted]")
    return text


def parse_sql_rows(text: str) -> list:
    """Rows from `spacetime sql` text output: the lines after the dashed separator."""
    lines = text.splitlines()
    for i, l in enumerate(lines):
        if re.fullmatch(r"[\s\-+]+", l) and "-" in l:
            return [[c.strip() for c in row.split("|")] for row in lines[i + 1:] if row.strip()]
    return []


# ---------------------------------------------------------------- real side effects (all injectable)

def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def run_sql(query: str) -> list:
    """Read-only SELECT through the local `spacetime` CLI as the logged-in owner (private tables included)."""
    exe = _spacetime()
    server = os.environ.get("SPACETIMEDB_SERVER", "local")
    db = os.environ.get("SPACETIMEDB_DB", "tech-bazaar")
    p = subprocess.run([exe, "sql", "-s", server, db, query], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        first = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(f"spacetime sql exited {p.returncode}: {first[0] if first else 'no output'}")
    return parse_sql_rows(p.stdout)


def _spacetime() -> str:
    from shutil import which
    return which("spacetime") or str(Path.home() / ".local" / "bin" / "spacetime")


def chrome_shot(url: str, path: str) -> tuple:
    if not Path(CHROME).exists():
        return False, "Google Chrome not found"
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--window-size=1440,900", "--virtual-time-budget=4000",
           f"--screenshot={path}", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return False, "chrome timed out after 45 s"
    if p.returncode != 0 or not Path(path).exists():
        return False, f"chrome exited {p.returncode}"
    return True, ""


# ---------------------------------------------------------------- one run

def run_checks(sql: Callable) -> tuple:
    results, notes = {}, {}
    for name, (query, ok, _what) in CHECKS.items():
        try:
            rows = sql(query)
        except Exception as e:  # reading is a courtesy: never a fake pass
            results[name] = "skipped"
            notes[name] = f"{type(e).__name__}: {e}"
            continue
        results[name] = "pass" if ok(rows) else "fail"
    return results, notes


def one_run(k: int, cmd: str, out: Path, args, secrets: list, sql, shoot, say) -> dict:
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    marks: list = []          # (beat, monotonic time the BEAT line arrived)
    last_line = ""
    shots: list = []
    shot_notes: list = []
    pool = ThreadPoolExecutor(max_workers=1)   # one Chrome at a time; never blocks the stage output
    futures: list = []

    def snap(label: str) -> None:
        if not args.screens:
            return
        for page in PAGES:
            path = out / "screens" / f"run{k}-{label}-{page}.png"
            url = f"http://localhost:{WEB_PORT}/{page}"

            def job(url=url, path=path, label=label, page=page):
                path.parent.mkdir(parents=True, exist_ok=True)
                ok, err = shoot(url, str(path))
                return (page, label, str(path.relative_to(out)) if ok else None, err)
            futures.append(pool.submit(job))

    log_path = out / f"run{k}.log"
    timed_out = False
    with open(log_path, "w") as log:
        proc = subprocess.Popen(shlex.split(cmd), cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        fired = threading.Event()

        def kill():
            fired.set()
            proc.kill()
        killer = threading.Timer(args.timeout, kill)
        killer.start()
        try:
            for raw in proc.stdout:
                line = redact(raw.rstrip("\n"), secrets)
                log.write(line + "\n")
                if line.strip():
                    last_line = line.strip()
                n = parse_beat(line)
                if n is not None:
                    if marks:
                        snap(f"beat{marks[-1][0]}")
                    marks.append((n, time.monotonic()))
            proc.wait()
        finally:
            killer.cancel()
            timed_out = fired.is_set()
    end = time.monotonic()
    if marks:
        snap(f"beat{marks[-1][0]}")
    else:
        snap("end")
    beats: dict = {}
    for i, (n, at) in enumerate(marks):
        nxt = marks[i + 1][1] if i + 1 < len(marks) else end
        beats[str(n)] = round(nxt - at, 2)
    for f in futures:
        page, label, rel, err = f.result()
        if rel:
            shots.append(rel)
        else:
            shot_notes.append(f"screenshot {label} {page}: {err}")
    pool.shutdown()
    checks, check_notes = run_checks(sql)
    entry = {"run": k, "started_at": started, "seconds": round(end - t0, 2), "beats": beats,
             "exit_code": proc.returncode, "checks": checks, "screenshots": shots,
             "last_beat": marks[-1][0] if marks else None, "last_line": last_line, "timed_out": timed_out,
             "check_notes": check_notes, "screenshot_notes": shot_notes}
    say(f"run {k}: exit {proc.returncode}, {entry['seconds']} s, checks "
        + ", ".join(f"{n}={v}" for n, v in checks.items()))
    return entry


# ---------------------------------------------------------------- report

def report_md(runs: list, cmd: str, args, started: str) -> str:
    L = [f"# Rehearsal report ({started})", "",
         f"Stage command: `{cmd}`", f"Runs: {len(runs)} of {args.runs}. Target: {TARGET_SECONDS} s per run (the 2:00 cut).", ""]
    head = "| Run | Total s | " + " | ".join(f"Beat {b} s" for b in BEATS) + " | Exit | Target | Checks |"
    L += [head, "|" + "---|" * (len(BEATS) + 5)]
    for r in runs:
        cells = " | ".join(str(r["beats"].get(b, "-")) for b in BEATS)
        c = r["checks"]
        checks = ", ".join(f"{n} {v}" for n, v in c.items())
        target = "within" if r["seconds"] <= TARGET_SECONDS else "over"
        L.append(f"| {r['run']} | {r['seconds']} | {cells} | {r['exit_code']} | {target} {TARGET_SECONDS} s | {checks} |")
    L.append("")
    timed = [(float(s), r["run"], b) for r in runs for b, s in r["beats"].items()]
    if timed:
        s, run, b = max(timed)
        L.append(f"Slowest beat: beat {b} in run {run} ({s} s).")
    else:
        L.append("Slowest beat: unknown (the stage command printed no `BEAT <n>` lines, so there are no per-beat timings).")
    passed = sum(1 for r in runs if r["exit_code"] == 0 and "fail" not in r["checks"].values())
    L += [f"Clean runs: {passed} of {len(runs)} (exit 0 and no failed check).", ""]
    problems = []
    for r in runs:
        if r["exit_code"] != 0:
            why = "timed out" if r["timed_out"] else f"exit {r['exit_code']}"
            beat = f"beat {r['last_beat']}" if r["last_beat"] else "before beat 1"
            problems.append(f"- Run {r['run']} failed ({why}) at {beat}. Last stage line: `{r['last_line']}`")
        for name, v in r["checks"].items():
            beat = f"after beat {r['last_beat']}" if r["last_beat"] else "after the run"
            if v == "fail":
                problems.append(f"- Run {r['run']} check {name} FAILED ({CHECKS[name][2]} was not true) {beat}. "
                                f"Last stage line: `{r['last_line']}`")
            elif v == "skipped":
                problems.append(f"- Run {r['run']} check {name} skipped: {r['check_notes'].get(name, 'no reason recorded')}")
        problems += [f"- Run {r['run']} {n}" for n in r["screenshot_notes"]]
    L += ["## Problems", ""] + (problems or ["None."]) + [""]
    L += ["## What the checks read", ""] + [f"- `{n}`: {w} (`{q}`)" for n, (q, _o, w) in CHECKS.items()] + [""]
    L.append("Logs: one `run<k>.log` per run beside this file (secret values replaced by `[redacted]`).")
    return "\n".join(L) + "\n"


def stack_down_md(down: list, at: str) -> str:
    ports = ", ".join(f"{h}:{p}" for h, p in down)
    return (f"# Rehearsal report\n\nstack down at {at}, not run.\n\nClosed: {ports}. "
            f"Start the local stack (`python3 scripts/launch.py up`), then run this again. Nothing was started or changed.\n")


# ---------------------------------------------------------------- CLI

def main(argv: Optional[list] = None, *, probe: Callable = port_open, sql: Callable = run_sql,
         shoot: Callable = chrome_shot, say: Callable = print) -> int:
    ap = argparse.ArgumentParser(description="Run the five-beat skeleton N times and record it")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--stage-cmd", help="command to run per rehearsal (default: demo/stage.py --auto if present, else bridge.py)")
    ap.add_argument("--out", default=str(ROOT / "demo" / "rehearsal" / datetime.now().strftime("%Y-%m-%d")))
    ap.add_argument("--screens", action="store_true", help="headless Chrome screenshots of /buyer and /market after each beat")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    ap.add_argument("--timeout", type=float, default=900, help="seconds before one run is killed (default 900)")
    args = ap.parse_args(argv)
    secrets = secret_values(dict(os.environ))
    cmd = args.stage_cmd or default_stage_cmd()
    out = Path(args.out).resolve()

    def say_r(s: str) -> None:
        say(redact(s, secrets))

    if args.dry_run:
        say_r(f"rehearse plan (dry run, nothing touched): {args.runs} run(s), one after another")
        say_r(f"  stage command: {redact(cmd, secrets)}")
        say_r(f"  preflight: {HOST}:{STDB_PORT} (SpacetimeDB) and {HOST}:{WEB_PORT} (web) must accept connections, else exit 2")
        say_r(f"  per run: wall time, seconds per beat from `BEAT <n>` lines, timeout {args.timeout:g} s")
        say_r("  end-state checks (read only): " + ", ".join(CHECKS))
        say_r("  screenshots: " + (f"yes, after each beat, pages {', '.join('/' + p for p in PAGES)}" if args.screens else "no (add --screens)"))
        say_r(f"  writes: {out}/REPORT.md, runs.json, run<k>.log" + (", screens/*.png" if args.screens else ""))
        say_r(f"  target: {TARGET_SECONDS} s per run (2:00)")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    down = [(h, p) for h, p in ((HOST, STDB_PORT), (HOST, WEB_PORT)) if not probe(h, p)]
    if down:
        at = datetime.now().strftime("%H:%M")
        (out / "REPORT.md").write_text(stack_down_md(down, at))
        (out / "runs.json").write_text("[]\n")
        say_r(f"stack down at {at}, not run (closed: {', '.join(f'{h}:{p}' for h, p in down)}). Report: {out}/REPORT.md")
        return 2
    runs = []
    for k in range(1, args.runs + 1):
        say_r(f"run {k} of {args.runs}: {redact(cmd, secrets)}")
        runs.append(one_run(k, cmd, out, args, secrets, sql, shoot, say_r))
    (out / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    (out / "REPORT.md").write_text(redact(report_md(runs, cmd, args, started), secrets))
    bad = any(r["exit_code"] != 0 or "fail" in r["checks"].values() for r in runs)
    say_r(f"report: {out}/REPORT.md ({'problems found' if bad else 'all clean'})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
