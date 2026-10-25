"""Startup self-check for Market identity token files (Maincloud mode)."""
import re

import market_env_check as chk

MAINCLOUD = {"SPACETIMEDB_SERVER": "maincloud"}


def test_seller_variable_names_match_the_seller_agents_market_identities():
    from agents.sellers import seller_agent
    assert set(chk.SELLER_TOKEN_VARS) == set(seller_agent._MARKET_SELLER_SUBJECT)
    for name, subject in seller_agent._MARKET_SELLER_SUBJECT.items():
        assert chk.SELLER_TOKEN_VARS[name] == f"SPACETIMEDB_{subject.replace('-', '_').upper()}_TOKEN_FILE"


def test_is_maincloud_reads_the_server_variable_only():
    assert chk.is_maincloud({"SPACETIMEDB_SERVER": "maincloud"})
    assert chk.is_maincloud({"SPACETIMEDB_SERVER": " https://maincloud.spacetimedb.com "})
    assert not chk.is_maincloud({"SPACETIMEDB_SERVER": "local"}) and not chk.is_maincloud({})
    assert not chk.is_maincloud({"SPACETIMEDB_SERVER": "http://127.0.0.1:3000"})


def test_a_maincloud_seller_without_its_token_variable_gets_one_loud_line_naming_it():
    line = chk.seller_line("seller_2", MAINCLOUD, exists=lambda p: True)
    assert line.startswith("MARKET IDENTITY MISSING: seller_2 ")
    assert "SPACETIMEDB_SELLER_B_TOKEN_FILE is not set" in line and "\n" not in line
    assert "SELLER_A" not in line and "SELLER_C" not in line


def test_a_token_variable_pointing_at_a_missing_file_is_named_without_printing_the_path():
    env = {**MAINCLOUD, "SPACETIMEDB_SELLER_A_TOKEN_FILE": "/secret/place/a.token"}
    line = chk.seller_line("seller_1", env, exists=lambda p: False)
    assert "SPACETIMEDB_SELLER_A_TOKEN_FILE points at a file that does not exist" in line
    assert "/secret" not in line and "a.token" not in line


def test_no_line_when_the_file_exists_the_market_is_local_or_the_seller_has_no_market_identity():
    env = {**MAINCLOUD, "SPACETIMEDB_SELLER_A_TOKEN_FILE": "/x/a"}
    assert chk.seller_line("seller_1", env, exists=lambda p: True) is None
    assert chk.seller_line("seller_1", {"SPACETIMEDB_SERVER": "local"}, exists=lambda p: False) is None
    assert chk.seller_line("seller_4", MAINCLOUD, exists=lambda p: False) is None   # no Market identity: bids go to the Buyer only
    assert chk.seller_line("seller_6", MAINCLOUD, exists=lambda p: False) is None   # MIRROR


def test_the_buyer_line_names_each_missing_variable():
    both = chk.buyer_line(MAINCLOUD, exists=lambda p: True)
    assert "SPACETIMEDB_BUYER_TOKEN_FILE is not set" in both and "SPACETIMEDB_REFEREE_TOKEN_FILE is not set" in both
    only_referee = chk.buyer_line({**MAINCLOUD, "SPACETIMEDB_BUYER_TOKEN_FILE": "/b"}, exists=lambda p: True)
    assert "SPACETIMEDB_REFEREE_TOKEN_FILE is not set" in only_referee and "BUYER_TOKEN_FILE is not set" not in only_referee
    assert chk.buyer_line({**MAINCLOUD, "SPACETIMEDB_BUYER_TOKEN_FILE": "/b", "SPACETIMEDB_REFEREE_TOKEN_FILE": "/r"},
                          exists=lambda p: True) is None
    assert chk.buyer_line({}, exists=lambda p: False) is None


def test_lines_use_no_em_or_en_dash():
    for line in (chk.seller_line("seller_1", MAINCLOUD), chk.buyer_line(MAINCLOUD)):
        assert not re.search("[" + chr(0x2013) + chr(0x2014) + "]", line)


def test_all_problems_lists_the_five_variables_when_nothing_is_set():
    assert [p.split(" ")[0] for p in chk.all_problems({}, exists=lambda p: True)] == [
        "SPACETIMEDB_SELLER_A_TOKEN_FILE", "SPACETIMEDB_SELLER_B_TOKEN_FILE", "SPACETIMEDB_SELLER_C_TOKEN_FILE",
        "SPACETIMEDB_BUYER_TOKEN_FILE", "SPACETIMEDB_REFEREE_TOKEN_FILE"]
