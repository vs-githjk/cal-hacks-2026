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
    "CRS_API_KEY": "crs_tok_SECRETTOKEN_5521",
}
NOW = datetime(2026, 10, 24, 9, 0, 0, tzinfo=timezone.utc)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path_factory):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    # Never read a real agents/.env while testing; tests that want one write their own.
    monkeypatch.setattr(S, "AGENTS_ENV", tmp_path_factory.mktemp("noenv") / ".env")
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


def signal(supplier_id="seller-grace", stability="verified_stable", checked_at=None, source="sandbox"):
    return {"supplier_id": supplier_id, "stability": stability, "source": source,
            "checked_at": checked_at or ts(NOW - timedelta(hours=1))}


def cache(tmp_path, entries=None, **kw):
    """A file in the shape agents/crs.py writes: supplier_id -> {persona_ref, signal, reason}."""
    if entries is None:
        entries = {"seller-grace": {"persona_ref": "persona_SECRETREF", "signal": signal(**kw), "reason": "SECRETREASON"}}
    p = tmp_path / "crs-signals.json"
    p.write_text(json.dumps(entries))
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
        assert "configured: no" in line and "not configured" in line
        want = "never" if line.startswith("CRS") else "none in this process"
        assert f"last call: {want}  " in line


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
    text = S.render([rows["Bright Data"], rows["Tiger Data"]])
    # Their status lives in module state, so a fresh process cannot say "never": it only knows none happened here.
    assert "last call: never" not in text
    assert text.count("last call: none in this process") == 2


CRS_CREDS = ("CRS_USERNAME", "CRS_PASSWORD")


def test_crs_reads_the_cached_signal(tmp_path, monkeypatch):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    ok = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert ok == {"name": "CRS", "configured": True, "last_call": ts(NOW - timedelta(hours=1)), "result": "verified"}
    adverse = by_name(S.collect(crs_cache=cache(tmp_path, stability="unstable")))["CRS"]
    assert adverse["result"] == "not_verified"
    recorded = by_name(S.collect(crs_cache=cache(tmp_path, source="recorded")))["CRS"]
    assert recorded["result"] == "verified"
    shown = json.dumps([ok, adverse, recorded]) + S.render([ok, adverse, recorded])
    assert "SECRETREF" not in shown and "SECRETREASON" not in shown and "seller-grace" not in shown


def test_crs_is_configured_with_user_and_password_and_no_base_url(tmp_path, monkeypatch):
    # The adapter falls back to its default sandbox URL, so CRS_BASE_URL is optional.
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    monkeypatch.delenv("CRS_BASE_URL", raising=False)
    row = by_name(S.collect(crs_cache=tmp_path / "none.json"))["CRS"]
    assert row["configured"] is True and row["result"] == "not_called" and row["last_call"] is None
    text = S.render([row])
    assert "configured: yes" in text
    assert SECRETS["CRS_USERNAME"] not in text and SECRETS["CRS_PASSWORD"] not in text


def test_crs_api_key_alone_is_configured_like_the_adapter(tmp_path, monkeypatch):
    # agents/crs.py _configured(): CRS_API_KEY or (CRS_USERNAME and CRS_PASSWORD).
    monkeypatch.setenv("CRS_API_KEY", SECRETS["CRS_API_KEY"])
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row == {"name": "CRS", "configured": True, "last_call": row["last_call"], "result": "verified"}
    assert row["last_call"] is not None
    assert SECRETS["CRS_API_KEY"] not in S.render([row])
    monkeypatch.setenv("CRS_API_KEY", "   ")
    assert by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]["configured"] is False


def write_agents_env(tmp_path, monkeypatch, body):
    f = tmp_path / "agents.env"
    f.write_text(body)
    monkeypatch.setattr(S, "AGENTS_ENV", f)
    return f


def test_crs_credentials_in_agents_env_count_as_configured(tmp_path, monkeypatch):
    # agents/README.md says to keep them in agents/.env; the adapter loads it through agents/common.py.
    write_agents_env(tmp_path, monkeypatch,
                     f"# comment\nCRS_USERNAME={SECRETS['CRS_USERNAME']}\nCRS_PASSWORD=\"{SECRETS['CRS_PASSWORD']}\"\n")
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row["configured"] is True and row["result"] == "verified" and row["last_call"] is not None
    text = S.render([row])
    assert SECRETS["CRS_USERNAME"] not in text and SECRETS["CRS_PASSWORD"] not in text
    # Reading the file does not export anything.
    import os
    assert "CRS_USERNAME" not in os.environ and "CRS_PASSWORD" not in os.environ


def test_crs_agents_env_api_key_and_empty_values(tmp_path, monkeypatch):
    write_agents_env(tmp_path, monkeypatch, f"CRS_API_KEY={SECRETS['CRS_API_KEY']}\n")
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row["configured"] is True
    assert SECRETS["CRS_API_KEY"] not in S.render([row])
    # An empty value in the file is skipped, as common.py does, so a lone username is not configured.
    write_agents_env(tmp_path, monkeypatch, f"CRS_USERNAME={SECRETS['CRS_USERNAME']}\nCRS_PASSWORD=\n")
    assert by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]["configured"] is False


def test_crs_real_environment_beats_agents_env(tmp_path, monkeypatch):
    # setdefault: a variable already in the environment (even empty) is not replaced by the file.
    write_agents_env(tmp_path, monkeypatch,
                     f"CRS_USERNAME={SECRETS['CRS_USERNAME']}\nCRS_PASSWORD={SECRETS['CRS_PASSWORD']}\n")
    monkeypatch.setenv("CRS_PASSWORD", "")
    assert by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]["configured"] is False


@pytest.mark.parametrize("missing", CRS_CREDS)
def test_crs_needs_both_user_and_password(tmp_path, monkeypatch, missing):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    monkeypatch.setenv(missing, "  ")
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row["configured"] is False and row["result"] == "not_configured" and row["last_call"] is None


def test_crs_default_cache_is_the_adapters_file():
    assert S.CRS_CACHE == ROOT / ".cache" / "crs-signals.json"


def test_crs_takes_the_newest_signal_across_suppliers(tmp_path, monkeypatch):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    older = signal("seller-a", "verified_stable", ts(NOW - timedelta(hours=5)))
    newest = signal("seller-b", "unstable", ts(NOW - timedelta(minutes=5)))
    entries = {
        "seller-a": {"persona_ref": "p1", "signal": older, "reason": "x"},
        "seller-b": {"persona_ref": "p2", "signal": newest, "reason": "y"},
        "seller-c": {"persona_ref": "p3", "signal": None, "reason": "CRS_CONSENT"},
        "seller-d": {"persona_ref": "p4", "signal": signal("seller-d", checked_at=ts(NOW - timedelta(days=1))), "reason": "z"},
    }
    row = by_name(S.collect(crs_cache=cache(tmp_path, entries)))["CRS"]
    assert row["last_call"] == ts(NOW - timedelta(minutes=5)) and row["result"] == "not_verified"


def test_crs_cache_without_a_signal_is_not_called(tmp_path, monkeypatch):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    entries = {"seller-c": {"persona_ref": "p3", "signal": None, "reason": "CRS_CONSENT"}}
    for data in (entries, {}):
        row = by_name(S.collect(crs_cache=cache(tmp_path, data)))["CRS"]
        assert row == {"name": "CRS", "configured": True, "last_call": None, "result": "not_called"}


def test_crs_cache_without_credentials_is_still_not_configured(tmp_path):
    row = by_name(S.collect(crs_cache=cache(tmp_path)))["CRS"]
    assert row["configured"] is False
    assert row["result"] == "not_configured"
    assert row["last_call"] is None


def test_crs_bad_files_are_errors_without_leaking(tmp_path, monkeypatch):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    row = by_name(S.collect(crs_cache=bad))["CRS"]
    assert row["result"] == "error" and row["last_call"] is None
    listy = tmp_path / "list.json"
    listy.write_text("[1, 2]")
    assert by_name(S.collect(crs_cache=listy))["CRS"]["result"] == "error"
    odd = cache(tmp_path, source="somewhere-else", stability="verified_stable")
    row = by_name(S.collect(crs_cache=odd))["CRS"]
    assert row["result"] == "error" and row["last_call"] is None
    assert "SECRETREF" not in json.dumps(row)


@pytest.mark.parametrize("stamp", ["not a date", "", None, 12345, "2026-13-45T99:00:00Z"])
def test_crs_unparseable_checked_at_is_an_error_not_a_last_call(tmp_path, monkeypatch, stamp):
    for k in CRS_CREDS:
        monkeypatch.setenv(k, SECRETS[k])
    entries = {"seller-grace": {"persona_ref": "p", "signal": {**signal(), "checked_at": stamp}, "reason": "r"}}
    row = by_name(S.collect(crs_cache=cache(tmp_path, entries)))["CRS"]
    assert row == {"name": "CRS", "configured": True, "last_call": None, "result": "error"}
    assert "not a date" not in S.render([row])


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
