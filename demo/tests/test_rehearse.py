"""Rehearsal harness: fake stage scripts, fake port probe, fake SQL, fake screenshots. No stack, no network, no Chrome."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from demo import rehearse

OK_STAGE = """\
import os, sys, time
for n in range(1, 6):
    print(f"BEAT {n} of 5: title {n}", flush=True)
    print(f"  line inside beat {n}", flush=True)
    time.sleep(0.05)
print("done", flush=True)
"""

FAIL_STAGE = """\
import sys, time
for n in range(1, 4):
    print(f"BEAT {n}", flush=True)
    time.sleep(0.02)
print("boom: stopped by the market at beat 3", flush=True)
sys.exit(1)
"""

# What a real Python stage does: plain print, no flush, stdout is a pipe. Without PYTHONUNBUFFERED in the child's env,
# every BEAT line arrives when the process exits and every beat reads 0 s.
UNFLUSHED_STAGE = """\
import time
for n in range(1, 6):
    print(f"BEAT {n} of 5: title {n}")
    time.sleep(0.3)
print("done")
"""

LEAKY_STAGE = """\
import os
print("BEAT 1", flush=True)
print("env is", os.environ.get("FAKE_API_KEY"), flush=True)
"""


def stage(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text(body)
    return f'{sys.executable} {p}'


def up(host, port):
    return True


def down(host, port):
    return False


def good_sql(query):
    if "FROM round_result" in query:
        return [["r1", "1"]]
    if "FROM payment" in query:
        return [["sim"]]
    if "FROM round" in query:
        return [["r1", "closed"], ["r2", "closed"]]
    raise AssertionError(query)


def no_shots(url, path):
    return True, ""


def run(tmp_path, cmd, *extra, probe=up, sql=good_sql, shoot=no_shots):
    out = tmp_path / "out"
    code = rehearse.main(["--stage-cmd", cmd, "--out", str(out), *extra], probe=probe, sql=sql, shoot=shoot)
    return code, out


def test_a_runs_n_times_and_writes_beat_seconds(tmp_path):
    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "3")
    runs = json.loads((out / "runs.json").read_text())
    assert code == 0
    assert [r["run"] for r in runs] == [1, 2, 3]
    for r in runs:
        assert r["exit_code"] == 0
        assert set(r["beats"]) == {"1", "2", "3", "4", "5"}
        assert all(v >= 0.04 for v in r["beats"].values())
        assert r["seconds"] >= sum(r["beats"].values()) - 0.05
        assert r["started_at"]
        assert set(r) >= {"run", "started_at", "seconds", "beats", "exit_code", "checks", "screenshots"}
    starts = [r["started_at"] for r in runs]
    assert starts == sorted(starts)


def test_b_failed_run_records_exit_and_last_beat_and_the_harness_continues(tmp_path):
    code, out = run(tmp_path, stage(tmp_path, "fail.py", FAIL_STAGE), "--runs", "2")
    runs = json.loads((out / "runs.json").read_text())
    assert code == 1
    assert len(runs) == 2, "run 2 must still happen after run 1 failed"
    assert runs[0]["exit_code"] == 1 and runs[0]["last_beat"] == 3
    assert "boom" in runs[0]["last_line"]
    assert "3" in runs[0]["beats"] and "4" not in runs[0]["beats"]
    report = (out / "REPORT.md").read_text()
    assert "beat 3" in report and "boom: stopped by the market at beat 3" in report


def test_c_preflight_refuses_when_stack_is_down(tmp_path):
    seen = []

    def probe(host, port):
        seen.append((host, port))
        return port != 3000

    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), probe=probe)
    assert code == 2
    assert ("127.0.0.1", 3000) in seen and ("127.0.0.1", 3100) in seen
    report = (out / "REPORT.md").read_text()
    assert "stack down at " in report and ", not run" in report
    assert "3000" in report
    assert json.loads((out / "runs.json").read_text()) == []


def test_d_report_has_table_and_the_two_minute_target(tmp_path):
    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "2")
    report = (out / "REPORT.md").read_text()
    header = next(l for l in report.splitlines() if l.startswith("| Run"))
    for col in ("Total s", "Beat 1 s", "Beat 5 s", "Checks"):
        assert col in header
    rows = [l for l in report.splitlines() if l.startswith("| 1 ") or l.startswith("| 2 ")]
    assert len(rows) == 2
    assert "2:00" in report and "120" in report
    assert "within" in report  # the fake run is far under 120 s


def test_e_default_stage_command(tmp_path):
    (tmp_path / "demo").mkdir()
    cmd = rehearse.default_stage_cmd(tmp_path)
    assert "bridge.py" in cmd and "--reset" in cmd and "--rounds 2" in cmd and "--step-delay 1" in cmd
    assert "stage.py" not in cmd
    (tmp_path / "demo" / "stage.py").write_text("")
    cmd = rehearse.default_stage_cmd(tmp_path)
    assert str(tmp_path / "demo" / "stage.py") in cmd and "--auto" in cmd and "bridge.py" not in cmd


def test_f_secrets_are_never_echoed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_API_KEY", "sk_test_Zq81xTopSecretValue")
    code, out = run(tmp_path, stage(tmp_path, "leak.py", LEAKY_STAGE), "--runs", "1")
    seen = capsys.readouterr()
    blob = seen.out + seen.err
    for p in out.rglob("*"):
        if p.is_file():
            blob += p.read_text(errors="replace")
    assert "sk_test_Zq81xTopSecretValue" not in blob
    assert "[redacted]" in blob


def test_checks_skipped_with_reason_when_sql_fails(tmp_path):
    def bad_sql(query):
        raise RuntimeError("spacetime not logged in")

    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "1", sql=bad_sql)
    r = json.loads((out / "runs.json").read_text())[0]
    assert set(r["checks"].values()) == {"skipped"}
    assert set(r["checks"]) == {"round_closed", "awarded_line", "payment_row", "round_2_present"}
    assert code == 0, "a skipped check is not a failure"
    report = (out / "REPORT.md").read_text()
    assert "spacetime not logged in" in report
    assert "Clean runs: 0 of 1" in report, "nothing was verified, so the run is not clean"
    assert "Unverified runs: 1 of 1" in report


def test_unverified_is_printed_instead_of_all_clean_when_checks_are_skipped(tmp_path):
    def bad_sql(query):
        raise RuntimeError("spacetime not on PATH")

    say = []
    out = tmp_path / "out"
    code = rehearse.main(["--stage-cmd", stage(tmp_path, "ok.py", OK_STAGE), "--out", str(out), "--runs", "1"],
                         probe=up, sql=bad_sql, shoot=no_shots, say=say.append)
    last = say[-1]
    assert code == 0
    assert "unverified" in last and "clean" not in last


def test_a_fully_passing_run_is_clean_and_not_unverified(tmp_path):
    say = []
    out = tmp_path / "out"
    code = rehearse.main(["--stage-cmd", stage(tmp_path, "ok.py", OK_STAGE), "--out", str(out), "--runs", "2"],
                         probe=up, sql=good_sql, shoot=no_shots, say=say.append)
    report = (out / "REPORT.md").read_text()
    assert code == 0 and "all clean" in say[-1]
    assert "Clean runs: 2 of 2" in report and "Unverified runs: 0 of 2" in report


def test_checks_fail_when_the_data_is_wrong(tmp_path):
    def sql(query):
        if "FROM round_result" in query:
            return []
        if "FROM payment" in query:
            return []
        return [["r1", "open"]]

    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "1", sql=sql)
    r = json.loads((out / "runs.json").read_text())[0]
    assert r["checks"] == {"round_closed": "fail", "awarded_line": "fail", "payment_row": "fail", "round_2_present": "fail"}
    assert code == 1


def test_checks_pass_on_good_data(tmp_path):
    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "1")
    assert set(json.loads((out / "runs.json").read_text())[0]["checks"].values()) == {"pass"}


def test_screens_one_per_page_per_beat_and_a_failure_is_not_fatal(tmp_path):
    calls = []

    def shoot(url, path):
        calls.append((url, Path(path).name))
        if "market" in url:
            return False, "chrome exited 1"
        Path(path).write_bytes(b"png")
        return True, ""

    code, out = run(tmp_path, stage(tmp_path, "ok.py", OK_STAGE), "--runs", "1", "--screens", shoot=shoot)
    r = json.loads((out / "runs.json").read_text())[0]
    assert code == 0
    assert len(calls) == 10, "5 beats x 2 pages"
    assert len(r["screenshots"]) == 5 and all("buyer" in s for s in r["screenshots"])
    assert "chrome exited 1" in (out / "REPORT.md").read_text()


def test_dry_run_prints_the_plan_and_touches_nothing(tmp_path, capsys):
    def boom(*a, **k):
        raise AssertionError("dry run must not touch the stack")

    out = tmp_path / "out"
    code = rehearse.main(["--runs", "3", "--dry-run", "--screens", "--out", str(out)], probe=boom, sql=boom, shoot=boom)
    text = capsys.readouterr().out
    assert code == 0
    assert not out.exists()
    for needle in ("3 run", "stage command", "3000", "3100", "round_closed", "buyer", "2:00"):
        assert needle in text


def test_beat_parser_accepts_the_stage_and_bridge_shapes():
    assert rehearse.parse_beat("  BEAT 4 of 5: Approval") == 4
    assert rehearse.parse_beat("BEAT 2: Shield") == 2
    assert rehearse.parse_beat("this is not a beat") is None
    assert rehearse.parse_beat("BEAT 9") is None


def test_timeout_kills_the_run(tmp_path):
    cmd = stage(tmp_path, "hang.py", "import time\nprint('BEAT 1', flush=True)\ntime.sleep(30)\n")
    code, out = run(tmp_path, cmd, "--timeout", "1")
    r = json.loads((out / "runs.json").read_text())[0]
    assert code == 1 and r["exit_code"] != 0 and r["timed_out"] is True


def test_parse_sql_rows_reads_the_cli_table():
    text = ' id   | state    \n------+----------\n "r1" | "closed" \n "r2" | "closed" \n'
    assert rehearse.parse_sql_rows(text) == [['"r1"', '"closed"'], ['"r2"', '"closed"']]
    assert rehearse.parse_sql_rows(" id | state \n----+------\n") == []
    assert rehearse.parse_sql_rows("") == []


def test_unflushed_stage_output_still_gives_real_beat_times_and_spread_out_screenshots(tmp_path):
    shot_times = []

    def shoot(url, path):
        shot_times.append(time.monotonic())
        Path(path).write_bytes(b"png")
        return True, ""

    code, out = run(tmp_path, stage(tmp_path, "unflushed.py", UNFLUSHED_STAGE), "--runs", "1", "--screens", shoot=shoot)
    r = json.loads((out / "runs.json").read_text())[0]
    assert code == 0
    assert set(r["beats"]) == {"1", "2", "3", "4", "5"}
    assert all(v >= 0.25 for v in r["beats"].values()), r["beats"]
    assert len(shot_times) == 10
    assert max(shot_times) - min(shot_times) >= 0.9, "screenshots must be taken as the beats happen, not all at the end"
