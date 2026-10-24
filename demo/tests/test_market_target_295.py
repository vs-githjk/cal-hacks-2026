"""#295: the market the bridge and stage talk to, from the env and the Lane D env file; tokens per market."""
import pytest

from demo import bridge, market_target as T

MAIN = {"SPACETIMEDB_SERVER": "maincloud", "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com", "SPACETIMEDB_DB": "tech-bazaar"}


def test_the_default_is_the_local_market():
    t = T.resolve(None, {})
    assert t == {"server": "local", "http": "http://127.0.0.1:3000", "db": "tech-bazaar", "local": True}


def test_the_env_file_names_maincloud_and_wins_over_the_process_env(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nSPACETIMEDB_SERVER=maincloud\nSPACETIMEDB_HTTP='https://maincloud.spacetimedb.com'\n"
                 "SPACETIMEDB_DB=tech-bazaar\nSTRIPE_SECRET_KEY=not-read\n")
    t = T.resolve(f, {})
    assert t["server"] == "maincloud" and not t["local"] and t["http"] == "https://maincloud.spacetimedb.com"
    assert T.resolve(f, {"SPACETIMEDB_DB": "tech-bazaar-test"})["db"] == "tech-bazaar"   # as scripts/launch.py: the file wins
    assert T.resolve(tmp_path / "missing", {"SPACETIMEDB_DB": "tech-bazaar-test"})["db"] == "tech-bazaar-test"


def test_export_lines_in_the_env_file_are_read(tmp_path):
    f = tmp_path / ".env"
    f.write_text("export SPACETIMEDB_SERVER=maincloud\nexport SPACETIMEDB_HTTP=https://maincloud.spacetimedb.com\n")
    t = T.resolve(f, {})
    assert t["server"] == "maincloud" and not t["local"]


@pytest.mark.parametrize("env, why", [
    ({**MAIN, "SPACETIMEDB_HTTP": "http://maincloud.spacetimedb.com"}, "https"),
    ({**MAIN, "SPACETIMEDB_DB": "Tech Bazaar"}, "database name"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://user@maincloud.spacetimedb.com"}, "plain"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com/v1/database"}, "plain"),
    ({**MAIN, "SPACETIMEDB_HTTP": "ftp://x"}, "plain"),
    ({"SPACETIMEDB_SERVER": "local", "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com"}, "same market"),
    ({**MAIN, "SPACETIMEDB_SERVER": "bad server!"}, "server"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://evil.example.com"}, "is not maincloud.spacetimedb.com"),
    ({**MAIN, "SPACETIMEDB_SERVER": "https://a.example.com", "SPACETIMEDB_HTTP": "https://b.example.com"}, "different hosts"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com:99999"}, "does not parse"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com/?db=x"}, "plain"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com/#x"}, "plain"),
])
def test_a_target_that_does_not_parse_is_refused(env, why):
    with pytest.raises(T.TargetError, match=why):
        T.resolve(None, env)


def test_tokens_are_per_market_and_a_shared_market_never_uses_the_local_tokens(tmp_path, monkeypatch):
    local, main = T.resolve(None, {}), T.resolve(None, MAIN)
    assert T.tokens_dir(local, tmp_path) == tmp_path / ".tokens"
    assert T.tokens_dir(main, tmp_path) == tmp_path / ".tokens" / "tech-bazaar@maincloud.spacetimedb.com"
    monkeypatch.setattr(T, "ROOT", tmp_path)
    (tmp_path / ".tokens").mkdir()
    for name in (bridge.REFEREE_TOKEN, bridge.BUYER_TOKEN):
        (tmp_path / ".tokens" / name).write_text("{}")         # local tokens exist
    with pytest.raises(SystemExit, match="local tokens are never used"):
        bridge.find_tokens_dir(None, main)
    own = tmp_path / ".tokens" / "tech-bazaar@maincloud.spacetimedb.com"
    own.mkdir()
    for name in (bridge.REFEREE_TOKEN, bridge.BUYER_TOKEN):
        (own / name).write_text("{}")
    assert bridge.find_tokens_dir(None, main) == own
    assert bridge.find_tokens_dir(str(own), main) == own
    with pytest.raises(SystemExit, match="not this market's own folder"):   # an explicit local dir is refused too
        bridge.find_tokens_dir(str(tmp_path / ".tokens"), main)
    monkeypatch.setenv("BRIDGE_TOKENS_DIR", str(tmp_path / ".tokens"))
    assert bridge.find_tokens_dir(None, main) == own                        # the env dir never replaces the market's own


def test_the_local_market_never_signs_with_a_shared_markets_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ROOT", tmp_path)
    own = tmp_path / ".tokens" / "tech-bazaar@maincloud.spacetimedb.com"
    own.mkdir(parents=True)
    for name in (bridge.REFEREE_TOKEN, bridge.BUYER_TOKEN):
        (own / name).write_text("{}")
    with pytest.raises(SystemExit, match="shared market's tokens"):
        bridge.find_tokens_dir(str(own), T.resolve(None, {}))
    monkeypatch.setenv("BRIDGE_TOKENS_DIR", str(own))
    with pytest.raises(SystemExit, match="shared market's tokens"):
        bridge.find_tokens_dir(None, None)


def test_export_sets_what_stdb_reads(monkeypatch):
    for k in T.NAMES:
        monkeypatch.delenv(k, raising=False)
    T.export(T.resolve(None, MAIN))
    import os
    assert os.environ["SPACETIMEDB_HTTP"] == "https://maincloud.spacetimedb.com" and os.environ["SPACETIMEDB_DB"] == "tech-bazaar"
    assert "shared market" in T.describe(T.resolve(None, MAIN))


@pytest.mark.parametrize("file_server, flag", [("maincloud", "local"), ("local", "maincloud")])
def test_a_server_flag_that_differs_from_the_env_file_is_refused(tmp_path, monkeypatch, file_server, flag):
    import types
    from demo import run_demo
    f = tmp_path / ".env"
    http = "https://maincloud.spacetimedb.com" if file_server == "maincloud" else "http://127.0.0.1:3000"
    f.write_text(f"SPACETIMEDB_SERVER={file_server}\nSPACETIMEDB_HTTP={http}\n")
    monkeypatch.setattr(run_demo, "DEFAULT_ENV_FILE", f)
    for k in T.NAMES:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit, match="--server"):
        bridge.live_target(types.SimpleNamespace(server=flag))
    assert bridge.live_target(types.SimpleNamespace(server=file_server))["server"] == file_server
    assert bridge.live_target(types.SimpleNamespace(server=None))["server"] == file_server


def test_a_symlink_to_a_shared_markets_tokens_counts_as_shared(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ROOT", tmp_path)
    own = tmp_path / ".tokens" / "tech-bazaar@maincloud.spacetimedb.com"
    own.mkdir(parents=True)
    for name in (bridge.REFEREE_TOKEN, bridge.BUYER_TOKEN):
        (own / name).write_text("{}")
    (tmp_path / "plain").symlink_to(own)
    with pytest.raises(SystemExit, match="shared market's tokens"):
        bridge.find_tokens_dir(str(tmp_path / "plain"), T.resolve(None, {}))
