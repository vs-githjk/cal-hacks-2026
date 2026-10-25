"""#449 RT-27: a public *-dev seed gives a public address. In production mode (mailbox) a process must not quietly
trust a peer whose seed env var is missing: it raises at startup. Offline, no agent is built."""
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

PRIVATE = "a-private-seed-of-24-chars!"


@pytest.fixture
def seeds(monkeypatch):
    """Every seed private; a test then puts one peer back on its public dev default."""
    for flag in ("AGENTS_MAILBOX", "BUYER_MAILBOX", "ADVOCATE_MAILBOX", "SELLERS_MAILBOX", "CALLER_MAILBOX",
                 "BUYER_DELEGATE_CALL"):
        monkeypatch.delenv(flag, raising=False)
    for role in ("buyer", "advocate", "caller", *common.CATALOG_SELLERS):
        monkeypatch.setitem(common.SEEDS, role, f"{PRIVATE}-{role}")
    return monkeypatch


def dev(monkeypatch, role):
    monkeypatch.setitem(common.SEEDS, role, f"tech-bazaar-{role}-dev")


def test_local_mode_keeps_the_dev_seeds_working(seeds):
    dev(seeds, "advocate")
    dev(seeds, "buyer")
    for role in ("buyer", "advocate", "seller_1", "caller"):
        common.require_peer_seeds(role)       # no mailbox flag: nothing is raised


@pytest.mark.parametrize("flag", ["AGENTS_MAILBOX", "BUYER_MAILBOX"])
def test_the_buyer_in_production_mode_needs_the_advocates_private_seed(seeds, flag):
    seeds.setenv(flag, "1")
    common.require_peer_seeds("buyer")        # all private: fine
    dev(seeds, "advocate")
    with pytest.raises(RuntimeError) as e:
        common.require_peer_seeds("buyer")
    assert "ADVOCATE_AGENT_SEED" in str(e.value) and "advocate" in str(e.value)


def test_a_missing_empty_seed_counts_as_missing_too(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    seeds.setitem(common.SEEDS, "advocate", "")
    with pytest.raises(RuntimeError, match="ADVOCATE_AGENT_SEED"):
        common.require_peer_seeds("buyer")


def test_the_buyer_needs_the_caller_seed_only_when_it_delegates_the_call(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    dev(seeds, "caller")
    common.require_peer_seeds("buyer")        # BUYER_DELEGATE_CALL off: the caller is not a peer
    seeds.setenv("BUYER_DELEGATE_CALL", "1")
    with pytest.raises(RuntimeError, match="CALLER_AGENT_SEED"):
        common.require_peer_seeds("buyer")


@pytest.mark.parametrize("role", ["advocate", "seller_1", "seller_3", "seller_5", "caller"])
def test_everyone_else_needs_the_buyers_private_seed(seeds, role):
    seeds.setenv("AGENTS_MAILBOX", "1")
    common.require_peer_seeds(role)
    dev(seeds, "buyer")
    with pytest.raises(RuntimeError, match="BUYER_AGENT_SEED"):
        common.require_peer_seeds(role)


def test_a_custom_seller_trusts_the_buyer_too(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    dev(seeds, "buyer")
    with pytest.raises(RuntimeError, match="BUYER_AGENT_SEED"):
        common.require_peer_seeds("my-custom-store")


def test_the_message_names_every_missing_peer_and_never_a_seed_value(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    seeds.setenv("BUYER_DELEGATE_CALL", "1")
    dev(seeds, "advocate")
    dev(seeds, "caller")
    with pytest.raises(RuntimeError) as e:
        common.require_peer_seeds("buyer")
    text = str(e.value)
    assert "ADVOCATE_AGENT_SEED" in text and "CALLER_AGENT_SEED" in text
    assert "tech-bazaar-advocate-dev" not in text and PRIVATE not in text


def test_shield_and_pulse_talk_to_no_agent_peer(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    dev(seeds, "buyer")
    dev(seeds, "advocate")
    common.require_peer_seeds("shield")
    common.require_peer_seeds("pulse")


# ---- the sellers the buyer trusts as senders (it already asks only the ones that can run) ----------------------------
def test_in_production_mode_a_seller_on_a_dev_seed_is_not_a_trusted_sender(seeds):
    dev(seeds, "seller_3")
    seeds.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))
    assert "seller_3" in common.trusted_sellers()          # local mode: every seller, as before
    seeds.setenv("AGENTS_MAILBOX", "1")
    trusted = common.trusted_sellers()
    assert "seller_3" not in trusted and {"seller_1", "seller_5"} <= set(trusted)


def test_the_buyer_builds_its_sender_table_from_the_trusted_sellers():
    src = Path(__file__).with_name("buyer").joinpath("buyer_agent.py").read_text()
    assert "SELLER_ADDRS = {common.address(s): s for s in common.trusted_sellers()}" in src


def test_a_sellers_address_is_trusted_only_with_a_private_seed_in_production_mode(seeds):
    """Market Pulse answers a seller's own record to the sender whose address is that seller's: not a public dev address."""
    dev(seeds, "seller_3")
    seeds.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))
    assert common.seller_address("seller_3") == common.address("seller_3")      # local mode: as before
    assert common.seller_address("no-such-seller") is None
    seeds.setenv("AGENTS_MAILBOX", "1")
    assert common.seller_address("seller_3") is None
    assert common.seller_address("seller_1") == common.address("seller_1")


def test_pulse_asks_for_the_trusted_seller_address():
    src = Path(__file__).with_name("pulse").joinpath("orchestrator.py").read_text()
    assert "own_addresses[seller_id] = common.seller_address(seller_id)" in src
    assert "common.address(seller_id)" not in src


# ---- startup wiring: each entry point checks before it runs ---------------------------------------------------------
@pytest.mark.parametrize("path", ["buyer/buyer_agent.py", "advocate/advocate_agent.py", "sellers/seller_agent.py",
                                  "sellers/run_all.py"])
def test_each_entry_point_checks_its_peers_before_it_runs(path):
    src = Path(__file__).with_name(path.split("/")[0]).joinpath(path.split("/")[1]).read_text()
    main = src[src.index('if __name__ == "__main__":'):]
    assert "common.require_peer_seeds(" in main or "require_peer_seeds(" in main
    assert main.index("require_peer_seeds(") < max(main.rfind(".run()"), main.rfind("bureau.run()"))


def test_the_advocate_refuses_to_start_in_production_mode_with_the_buyer_on_a_dev_seed(seeds):
    seeds.setenv("AGENTS_MAILBOX", "1")
    dev(seeds, "buyer")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    with patch("uagents.Agent") as fake_class:
        with pytest.raises(RuntimeError, match="BUYER_AGENT_SEED"):
            runpy.run_module("advocate.advocate_agent", run_name="__main__")
    fake_class.return_value.run.assert_not_called()
