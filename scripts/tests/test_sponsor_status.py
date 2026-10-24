"""T14: one honest line per sponsor. No network, no secrets in the output.
Run: python3 -m pytest scripts/tests/test_sponsor_status.py -q"""
import importlib.util
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("sponsor_status", ROOT / "scripts" / "sponsor_status.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["sponsor_status"] = S
_spec.loader.exec_module(S)

from data.baselines import brightdata  # noqa: E402
from data.tiger import store as tiger  # noqa: E402

ENV_NAMES = ("BRIGHT_DATA_API_KEY", "BRIGHT_DATA_MAX_CALLS", "TIGER_DATA_SERVICE_URL",
             "CRS_USERNAME", "CRS_PASSWORD", "CRS_BASE_URL", "CRS_API_KEY")
SECRETS = {
    "BRIGHT_DATA_API_KEY": "bd_SUPERSECRETKEY_91827",
    "TIGER_DATA_SERVICE_URL": "postgres://tigeruser:tigerpass_SECRET@tigerhost-xyz.example.com:5432/tsdb",
    "CRS_USERNAME": "crs_user_SECRETNAME",
    "CRS_PASSWORD": "crs_pass_SECRETWORD",
    "CRS_BASE_URL": "https://crs-secret-host.example.com/api",
}
NOW = datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    brightdata.reset()
    saved = dict(tiger._state)
    tiger._state.update({"last_call": None, "last_result": "not_configured"})
    yield
    tiger._state.clear()
    tiger._state.update(saved)
    brightdata.reset()


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("network attempted")

    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    return calls


def cache(tmp_path, **kw):
    rec = {"seller_id": "seller-grace", "verified": True, "reason_codes": [], "product": "fraud_finder",
           "checked_at": ts(NOW - timedelta(hours=1)), "origin": "SANDBOX"}
    rec.update(kw)
    p = tmp_path / "crs_last_check.json"
    p.write_text(json.dumps(rec))
    return p


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_no_env_lists_three_sponsors_not_configured_without_network(tmp_path, no_network):
    rows = S.collect(crs_cache=tmp_path / "missing.json")
    assert [r["name"] for r in rows] == ["Bright Data", "CRS", "Tiger Data"]
    for r in rows:
        assert r["configured"] is False
        assert r["last_call"] is None
        assert r["result"] == "not_configured"
    assert no_network == []
    text = S.render(rows)
    assert len(text.splitlines()) == 3
    for line in text.splitlines():
        assert "configured: no" in line and "not configured" in line and "last call: never" in line


def test_configured_modules_show_last_call_time_and_result(tmp_path, monkeypatch, no_network):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", SECRETS["BRIGHT_DATA_API_KEY"])
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", SECRETS["TIGER_DATA_SERVICE_URL"])
    brightdata._state.update({"last_call": "2026-10-24T08:15:00Z", "last_result": "ok"})
    tiger._state.update({"last_call": "2026-10-24T08:20:00Z", "last_result": "error"})
    rows = by_name(S.collect(crs_cache=cache(tmp_path)))
    assert rows["Bright Data"] == {"name": "Bright Data", "configured": True, "last_call": "2026-10-24T08:15:00Z", "result": "ok"}
    assert rows["Tiger Data"]["configured"] is True
    assert rows["Tiger Data"]["last_call"] == "2026-10-24T08:20:00Z"
    assert rows["Tiger Data"]["result"] == "error"
    text = S.render(list(rows.values()))
    assert "2026-10-24T08:15:00Z" in text and "configured: yes" in text
    assert no_network == []


def test_configured_but_never_called_says_so(monkeypatch):
    monkeypatch.setenv("BRIGHT_DATA_API_KEY", SECRETS["BRIGHT_DATA_API_KEY"])
    monkeypatch.setenv("TIGER_DATA_SERVICE_URL", SECRETS["TIGER_DATA_SERVICE_URL"])
    rows = by_name(S.collect(crs_cache=Path("/nonexistent/crs.json")))
    assert rows["Bright Data"]["configured"] is True and rows["Bright Data"]["last_call"] is None
    assert rows["Bright Data"]["result"] == "not_called"
    assert rows["Tiger Data"]["result"] == "not_called"
    assert "last call: never" in S.render(list(rows.values()))


def test_crs_reads_the_cached_check_record(tmp_path, monkeypatch):
    for k in ("CRS_USERNAME", "CRS_PASSWORD", "CRS_BASE_URL"):
        monkeypatch.setenv(k, SECRETS[k])
    ok = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert ok == {"name": "CRS", "configured": True, "last_call": ts(NOW - timedelta(hours=1)), "result": "verified"}
    blocked = by_name(S.collect(crs_cache=cache(tmp_path, verified=False, reason_codes=["risk_score_high"])))["CRS"]
    assert blocked["result"] == "not_verified"
    assert "risk_score_high" not in json.dumps(blocked)


def test_crs_cache_without_credentials_is_still_not_configured(tmp_path):
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row["configured"] is False
    assert row["result"] == "not_configured"
    assert row["last_call"] is None


def test_crs_not_configured_record_and_bad_files(tmp_path, monkeypatch):
    for k in ("CRS_USERNAME", "CRS_PASSWORD", "CRS_BASE_URL"):
        monkeypatch.setenv(k, SECRETS[k])
    nc = by_name(S.collect(crs_cache=cache(tmp_path, origin="NOT_CONFIGURED", verified=False)))["CRS"]
    assert nc["result"] == "not_configured"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    row = by_name(S.collect(crs_cache=bad))["CRS"]
    assert row["result"] == "error" and row["last_call"] is None
    odd = cache(tmp_path, ssn="123-45-6789")
    row = by_name(S.collect(crs_cache=odd))["CRS"]
    assert row["result"] == "error"
    assert "123-45-6789" not in json.dumps(row)


def test_output_never_contains_an_env_value(tmp_path, monkeypatch, capsys):
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("BRIGHT_DATA_MAX_CALLS", "77123")
    out_json = tmp_path / "status.json"
    brightdata._state.update({"last_call": "2026-10-24T08:15:00Z", "last_result": "ok"})
    rc = S.main(["--json", str(out_json), "--crs-cache", str(cache(tmp_path))])
    assert rc == 0
    printed = capsys.readouterr().out
    written = out_json.read_text()
    for v in list(SECRETS.values()) + ["77123", "tigerpass", "tigerhost", "crs-secret-host"]:
        assert v not in printed
        assert v not in written


def test_a_failing_status_becomes_an_error_row_without_its_message(tmp_path, monkeypatch):
    def broken():
        raise RuntimeError("password=hunter2 leaked")

    monkeypatch.setattr(brightdata, "status", broken)
    rows = by_name(S.collect(crs_cache=tmp_path / "none.json"))
    assert rows["Bright Data"]["result"] == "error"
    assert "hunter2" not in json.dumps(rows) and "hunter2" not in S.render(list(rows.values()))


def test_json_file_shape_and_main_prints_three_lines(tmp_path, capsys):
    out_json = tmp_path / "sub" / "status.json"
    rc = S.main(["--json", str(out_json), "--crs-cache", str(tmp_path / "none.json")])
    assert rc == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 3
    data = json.loads(out_json.read_text())
    assert set(data) == {"generated_at", "sponsors"}
    assert data["generated_at"].endswith("Z")
    assert [s["name"] for s in data["sponsors"]] == ["Bright Data", "CRS", "Tiger Data"]
    assert all(set(s) == {"name", "configured", "last_call", "result"} for s in data["sponsors"])


def test_committed_json_says_not_configured_and_has_no_dash_or_secret():
    path = ROOT / "web" / "public" / "sponsor-status.json"
    data = json.loads(path.read_text())
    assert all(s["configured"] is False and s["result"] == "not_configured" and s["last_call"] is None
               for s in data["sponsors"])
    raw = path.read_text()
    assert "—" not in raw and "–" not in raw


def test_cli_runs_as_a_module_with_no_keys(tmp_path):
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if k not in ENV_NAMES}
    r = subprocess.run([sys.executable, "-m", "scripts.sponsor_status", "--crs-cache", str(tmp_path / "none.json")],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("not configured") == 3
