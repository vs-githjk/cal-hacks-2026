"""#295: the market the bridge and stage talk to, from the env and the Lane D env file; tokens per market."""
import pytest

from demo import bridge, market_target as T

MAIN = {"SPACETIMEDB_SERVER": "maincloud", "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com", "SPACETIMEDB_DB": "tech-bazaar"}


def test_the_default_is_the_local_market():
    t = T.resolve(None, {})
    assert t == {"server": "local", "http": "http://127.0.0.1:3000", "db": "tech-bazaar", "local": True}


def test_the_env_file_names_maincloud_and_the_process_env_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nSPACETIMEDB_SERVER=maincloud\nSPACETIMEDB_HTTP='https://maincloud.spacetimedb.com'\n"
                 "SPACETIMEDB_DB=tech-bazaar\nSTRIPE_SECRET_KEY=not-read\n")
    t = T.resolve(f, {})
    assert t["server"] == "maincloud" and not t["local"] and t["http"] == "https://maincloud.spacetimedb.com"
    assert T.resolve(f, {"SPACETIMEDB_DB": "tech-bazaar-test"})["db"] == "tech-bazaar-test"


@pytest.mark.parametrize("env, why", [
    ({**MAIN, "SPACETIMEDB_HTTP": "http://maincloud.spacetimedb.com"}, "https"),
    ({**MAIN, "SPACETIMEDB_DB": "Tech Bazaar"}, "database name"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://user@maincloud.spacetimedb.com"}, "plain"),
    ({**MAIN, "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com/v1/database"}, "plain"),
    ({**MAIN, "SPACETIMEDB_HTTP": "ftp://x"}, "plain"),
    ({"SPACETIMEDB_SERVER": "local", "SPACETIMEDB_HTTP": "https://maincloud.spacetimedb.com"}, "same market"),
    ({**MAIN, "SPACETIMEDB_SERVER": "bad server!"}, "server"),
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


def test_export_sets_what_stdb_reads(monkeypatch):
    for k in T.NAMES:
        monkeypatch.delenv(k, raising=False)
    T.export(T.resolve(None, MAIN))
    import os
    assert os.environ["SPACETIMEDB_HTTP"] == "https://maincloud.spacetimedb.com" and os.environ["SPACETIMEDB_DB"] == "tech-bazaar"
    assert "shared market" in T.describe(T.resolve(None, MAIN))
