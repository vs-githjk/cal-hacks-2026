"""SellerConfig contract and factory: bad configs are refused with field errors, all five sellers validate."""
import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
import factory
from factory import ConfigError, load_config, seller_from_config, validate_config
from policy import CATALOG, make_bid, seller

import run_all

SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "SellerConfig.schema.json"
GPU_TI, PSU = "rtx 5070 ti", "psu 750w"


def good():
    return {
        "id": "corner-pc", "name": "Corner PC", "owner": "Sam", "archetype": "local shop", "origin": "SIM",
        "pricing": {"mode": "discount", "discount": 0.05}, "perks": ["30-day returns"], "claims": ["new, sealed"],
        "listings": {GPU_TI: {
            "price": 1300.0, "floor_by_condition": {"new": 1200.0}, "condition": "new", "page_condition": "new",
            "variant": "retail", "listing_url": "https://example.com/sim/corner-pc/rtx-5070-ti",
            "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti", "length_mm": 303}}},
    }


def need(*skus):
    return {"id": "need-1", "buyer_id": "b1", "consent": True, "auction_window_s": 60, "source": "simulated",
            "items": [{"sku_spec": s, "condition": "new", "variant": "retail", "quantity": 1} for s in skus]}


def refused(cfg, *words):
    with pytest.raises(ValueError) as e:
        validate_config(cfg)
    assert isinstance(e.value, ConfigError)
    for w in words:
        assert w in str(e.value), (w, str(e.value))
    return e.value


def test_valid_config_loads_and_is_normalized(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(good()))
    cfg = load_config(p)
    assert cfg["id"] == "corner-pc" and cfg["shipping"] == 0
    assert cfg["listings"][GPU_TI]["floor_by_condition"] == {"new": 1200.0}


def test_load_config_refuses_bad_json_and_missing_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{nope")
    with pytest.raises(ValueError):
        load_config(p)
    with pytest.raises(ValueError):
        load_config(tmp_path / "missing.json")


def test_negative_or_zero_floor_refused():
    for bad in (-1, 0):
        cfg = good()
        cfg["listings"][GPU_TI]["floor_by_condition"]["new"] = bad
        refused(cfg, f"listings.{GPU_TI}.floor_by_condition.new")


def test_floor_above_price_refused():
    cfg = good()
    cfg["listings"][GPU_TI]["floor_by_condition"]["new"] = 1400.0
    err = refused(cfg, f"listings.{GPU_TI}.floor_by_condition.new", "above")
    assert err.errors[0]["field"] == f"listings.{GPU_TI}.floor_by_condition.new"


def test_unknown_condition_refused():
    cfg = good()
    cfg["listings"][GPU_TI]["condition"] = "mint"
    refused(cfg, f"listings.{GPU_TI}.condition")
    cfg = good()
    cfg["listings"][GPU_TI]["floor_by_condition"]["mint"] = 10
    refused(cfg, "floor_by_condition", "mint")
    cfg = good()
    cfg["listings"][GPU_TI]["page_condition"] = "pristine"
    refused(cfg, "page_condition")


def test_bad_listing_urls_refused():
    for url in ("javascript:alert(1)", "ftp://example.com/x", "https://", "data:text/html,hi", "//example.com/x", ""):
        cfg = good()
        cfg["listings"][GPU_TI]["listing_url"] = url
        refused(cfg, f"listings.{GPU_TI}.listing_url")
    cfg = good()
    cfg["listings"][GPU_TI]["listing_url"] = "http://example.com/ok"
    validate_config(cfg)


def test_floor_must_cover_the_offered_condition():
    cfg = good()
    cfg["listings"][GPU_TI]["floor_by_condition"] = {"open-box": 1000.0}
    refused(cfg, f"listings.{GPU_TI}.floor_by_condition", "new")


def test_pricing_mode_needs_its_own_field_and_a_sane_value():
    cfg = good()
    cfg["pricing"] = {"mode": "fixed_margin", "margin_pct": 20}   # listing has price, not cost
    refused(cfg, f"listings.{GPU_TI}.cost")
    cfg = good()
    cfg["pricing"] = {"mode": "fixed_margin"}
    refused(cfg, "pricing.margin_pct")
    cfg = good()
    cfg["pricing"] = {"mode": "discount", "discount": 0.95}
    refused(cfg, "pricing.discount")
    cfg = good()
    cfg["pricing"] = {"mode": "haggle"}
    refused(cfg, "pricing.mode")
    cfg = good()
    del cfg["listings"][GPU_TI]["price"]
    refused(cfg, f"listings.{GPU_TI}.price")


def test_missing_and_unexpected_fields_refused():
    cfg = good()
    del cfg["name"]
    refused(cfg, "name")
    cfg = good()
    cfg["listings"] = {}
    refused(cfg, "listings")
    cfg = good()
    cfg["id"] = "../../etc/passwd"
    refused(cfg, "id")
    cfg = good()
    cfg["listings"][GPU_TI]["secret"] = 1
    refused(cfg, "secret")
    refused([], "config")


def test_all_errors_are_reported_together():
    cfg = good()
    cfg["listings"][GPU_TI]["floor_by_condition"]["new"] = -5
    cfg["listings"][GPU_TI]["listing_url"] = "javascript:x"
    err = refused(cfg)
    assert {e["field"] for e in err.errors} >= {f"listings.{GPU_TI}.floor_by_condition.new",
                                                f"listings.{GPU_TI}.listing_url"}


def test_fixed_margin_price_is_cost_times_margin():
    cfg = good()
    cfg["pricing"] = {"mode": "fixed_margin", "margin_pct": 15}
    ls = cfg["listings"][GPU_TI]
    del ls["price"]
    ls["cost"] = 1000.0
    ls["floor_by_condition"]["new"] = 1100.0
    s = seller_from_config(cfg)
    assert s["listings"][GPU_TI]["price"] == pytest.approx(1150.0)
    bid = make_bid(need(GPU_TI), s)
    assert bid["lines"][0]["unit_price"] == 1150.0
    assert "margin" in bid["decision_trace"] and "discount" not in bid["decision_trace"]


def test_fixed_margin_floor_above_marked_up_price_refused():
    cfg = good()
    cfg["pricing"] = {"mode": "fixed_margin", "margin_pct": 5}
    ls = cfg["listings"][GPU_TI]
    del ls["price"]
    ls["cost"] = 1000.0
    ls["floor_by_condition"]["new"] = 1100.0
    refused(cfg, f"listings.{GPU_TI}.floor_by_condition.new")


def test_discount_mode_bid_respects_floor_and_origin():
    s = seller_from_config(good())
    bid = make_bid(need(GPU_TI), s)
    assert bid["lines"][0]["unit_price"] == 1235.0 and bid["origin"] == "SIM"
    common.validate("Bid", bid)


def test_schema_file_is_a_valid_json_schema_and_accepts_good():
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(good())


@pytest.mark.parametrize("sid", ["buyer", "advocate", "shield", "seller_1", "seller_5", "seller_12",
                                 "seller-1", "seller-5", "seller-12", "seller-01",
                                 "seller_1_agent", "seller-1-agent", "seller_5_agent", "buyer_agent",
                                 "advocate_agent", "shield_agent", "shield-agent"])
def test_reserved_agent_ids_are_refused(sid):
    err = refused(dict(good(), id=sid), "id", "reserved for a Fish Market agent")
    assert [e["field"] for e in err.errors] == ["id"]


def test_similar_but_unreserved_ids_are_accepted():
    for sid in ("seller-one", "seller_one", "myseller_1", "my-seller-1", "buyer-2", "shield_x", "seller-1a",
                "buyer_agent_2", "shield_agent_x", "seller-1-agents"):
        assert validate_config(dict(good(), id=sid))["id"] == sid


@pytest.mark.parametrize("sid", ["seller-1", "seller-5", "seller_1", "seller_1_agent", "seller-1-agent",
                                 "buyer_agent", "shield_agent"])
def test_hyphen_ids_never_read_a_built_in_sellers_seed(sid, monkeypatch):
    """A hyphen id maps to the same env name as the built-in (seller-1 -> SELLER_1_AGENT_SEED), so it must be refused
    by the factory and, even if a caller skips the factory, by register_custom_seller."""
    monkeypatch.setenv("SELLER_1_AGENT_SEED", "reviewer-fake-seed-xyz")
    monkeypatch.setenv("SELLER_5_AGENT_SEED", "reviewer-fake-seed-xyz")
    monkeypatch.setenv("BUYER_AGENT_SEED", "reviewer-fake-seed-xyz")
    monkeypatch.setenv("SHIELD_AGENT_SEED", "reviewer-fake-seed-xyz")
    before = dict(common.SEEDS)
    with pytest.raises(ConfigError):
        seller_from_config(dict(good(), id=sid))
    with pytest.raises(ValueError, match="already a Fish Market agent"):
        common.register_custom_seller(sid)
    assert common.SEEDS == before


def test_catalog_sellers_may_use_their_reserved_ids():
    assert validate_config({"id": "seller_1", **CATALOG["sellers"]["seller_1"]}, catalog=True)["id"] == "seller_1"
    with pytest.raises(ConfigError):
        seller_from_config({"id": "seller_1", **CATALOG["sellers"]["seller_1"]})


@pytest.mark.parametrize("role", ["buyer", "advocate", "shield", "seller_1", "seller_4"])
def test_register_custom_seller_refuses_an_existing_agent_role(role):
    before = common.SEEDS[role]
    with pytest.raises(ValueError, match="already a Fish Market agent"):
        common.register_custom_seller(role)
    assert common.SEEDS[role] == before


@pytest.mark.parametrize("port,owner", [(8011, "seller_1"), (8001, "buyer"), (3000, "SpacetimeDB"), (8787, "shield")])
def test_reserved_ports_are_refused_with_the_service_named(port, owner):
    err = refused(dict(good(), port=port), "port", owner)
    assert [e["field"] for e in err.errors] == ["port"]


def test_a_free_custom_port_is_accepted():
    assert validate_config(dict(good(), port=9123))["port"] == 9123


def test_headline_total_uses_only_the_lines_the_buyer_allows():
    """Shop X: new $1000 plus open-box $900. Shop Y: new $1050. The need is new: Shop X must beat Shop Y at $1000."""
    def shop(sid, price, alt=None):
        cfg = good()
        cfg["id"] = sid
        ls = cfg["listings"][GPU_TI]
        ls["price"], ls["floor_by_condition"] = price, {"new": price - 100}
        if alt:
            ls["alt_lines"] = [{"condition": "open-box", "price": alt}]
            ls["floor_by_condition"]["open-box"] = alt - 100
        cfg["pricing"] = {"mode": "discount", "discount": 0}
        return seller_from_config(cfg)

    x, y = shop("shop-x", 1000.0, alt=900.0), shop("shop-y", 1050.0)
    n = need(GPU_TI)
    bid_x, bid_y = make_bid(n, x), make_bid(n, y)
    assert bid_x["total_landed_price"] == 1000.0 < bid_y["total_landed_price"] == 1050.0
    assert [l["offered_condition"] for l in bid_x["lines"]] == ["new"]
    # allowed_conditions widens the set: both lines are bid and the cheaper allowed one sets the total
    wide = copy.deepcopy(n)
    wide["items"][0]["allowed_conditions"] = ["new", "open-box"]
    bid_wide = make_bid(wide, x)
    assert bid_wide["total_landed_price"] == 900.0
    assert sorted(l["offered_condition"] for l in bid_wide["lines"]) == ["new", "open-box"]
    # nothing allowed among its lines: today's behaviour, every line bid and the cheapest sets the total
    refurb = copy.deepcopy(n)
    refurb["items"][0]["condition"] = "refurbished"
    bid_none = make_bid(refurb, x)
    assert bid_none["total_landed_price"] == 900.0 and len(bid_none["lines"]) == 2


@pytest.fixture
def event_loop_for_agents():
    """uagents.Agent reads the current event loop; other test files can leave none set."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()


def test_run_all_in_mailbox_mode_skips_sellers_with_a_public_seed(monkeypatch, capsys, event_loop_for_agents):
    for k in ("AGENTS_MAILBOX", "SELLER_4_AGENT_SEED", "SELLER_5_AGENT_SEED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SELLERS_MAILBOX", "1")
    monkeypatch.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))  # seller_6 (MIRROR): test_seller_6.py
    for s in ("seller_1", "seller_2", "seller_3"):
        monkeypatch.setitem(common.SEEDS, s, f"private-{s}")
    agents = run_all.build_all()  # must not raise SystemExit
    out = capsys.readouterr().out
    assert [a.name for a in agents] == [seller(s)["name"] for s in ("seller_1", "seller_3")]   # #398: seller_2 is not run
    assert "seller_5 skipped: set SELLER_5_AGENT_SEED" in out and "seller_2 not run" in out and "seller_4 not run" in out


def test_run_all_builds_every_seller_without_mailbox_mode(monkeypatch, event_loop_for_agents):
    for k in ("AGENTS_MAILBOX", "SELLERS_MAILBOX"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(common, "SELLERS", list(common.CATALOG_SELLERS))  # seller_6 (MIRROR): test_seller_6.py
    assert len(run_all.build_all()) == 3   # #398: seller_1, seller_3, seller_5; seller_2 and seller_4 are not run
    assert len(run_all.build_all(["seller_2", "seller_4"])) == 2   # named explicitly, a retired seller still builds


def test_a_single_seller_agent_in_mailbox_mode_with_a_public_seed_still_exits(monkeypatch):
    monkeypatch.setenv("SELLERS_MAILBOX", "1")
    monkeypatch.setitem(common.SEEDS, "seller_4", "tech-bazaar-seller_4-dev")
    assert not common.mailbox_ready("seller_4")
    with pytest.raises(SystemExit):
        common.agent_args("seller_4", 8014)


def test_all_five_sellers_validate_against_the_schema():
    schema = json.loads(SCHEMA.read_text())
    sellers = CATALOG["sellers"]
    assert sorted(sellers) == [f"seller_{i}" for i in range(1, 6)]
    for sid, entry in sellers.items():
        cfg = {"id": sid, **entry}
        Draft202012Validator(schema).validate(cfg)
        validate_config(cfg, catalog=True)
        assert cfg["origin"] == "SIM"
    assert common.CATALOG_SELLERS == [f"seller_{i}" for i in range(1, 6)]


def test_existing_sellers_keep_their_prices():
    gpu = "rtx 4070 super 12gb"
    assert make_bid(need(gpu), seller("seller_1"))["lines"][0]["unit_price"] == 581.99
    assert make_bid(need(gpu), seller("seller_3"))["lines"][0]["unit_price"] == 518.42
    assert seller("seller_2")["listings"][gpu]["floor"] == 535.0


@pytest.mark.parametrize("sid", ["seller_4", "seller_5"])
def test_new_sellers_bid_on_the_5070_ti_need(sid):
    s = seller(sid)
    bid = make_bid(need(GPU_TI, PSU), s)
    common.validate("Bid", bid)
    assert bid["origin"] == "SIM" and bid["floor_check_passed"] and bid["supplier_id"] == sid
    gpu_lines = [l for l in bid["lines"] if l["sku_spec"] == GPU_TI]
    assert gpu_lines
    for line in gpu_lines:
        assert line["listing_url"].startswith("https://example.com/")
        assert line["attrs"]["chipset"] == "RTX 5070 Ti" and line["attrs"]["length_mm"] > 0


def test_seller_4_is_a_local_shop_on_fixed_margin():
    cfg = {"id": "seller_4", **CATALOG["sellers"]["seller_4"]}
    assert cfg["name"] == "Bay Area PC Shop" and cfg["pricing"]["mode"] == "fixed_margin"
    assert all("cost" in l and "price" not in l for l in cfg["listings"].values())
    line = make_bid(need(GPU_TI), seller("seller_4"))["lines"][0]
    ls = cfg["listings"][GPU_TI]
    assert line["unit_price"] == round(ls["cost"] * (1 + cfg["pricing"]["margin_pct"] / 100), 2)


def test_seller_5_bids_refurbished_and_open_box_lines_never_below_each_floor():
    cfg = {"id": "seller_5", **CATALOG["sellers"]["seller_5"]}
    assert cfg["name"] == "ReNew Refurb"
    bid = make_bid(need(GPU_TI), seller("seller_5"))
    lines = [l for l in bid["lines"] if l["sku_spec"] == GPU_TI]
    assert {l["offered_condition"] for l in lines} == {"refurbished", "open-box"}
    floors = cfg["listings"][GPU_TI]["floor_by_condition"]
    for l in lines:
        assert l["unit_price"] >= floors[l["offered_condition"]]
        assert l["page_condition"] == l["offered_condition"]
    # alternatives, not a basket: the headline total counts only the cheapest line per SKU
    assert bid["total_landed_price"] == round(min(l["unit_price"] for l in lines) + seller("seller_5")["shipping"], 2)


def test_below_floor_alternative_line_is_raised_to_its_own_floor():
    s = copy.deepcopy(seller("seller_5"))
    s["discount"] = 0.9
    bid = make_bid(need(GPU_TI), s)
    floors = {l["condition"]: l["floor"] for l in [s["listings"][GPU_TI], *s["listings"][GPU_TI]["alt_lines"]]}
    for l in bid["lines"]:
        assert l["unit_price"] == floors[l["offered_condition"]]
    assert bid["floor_check_passed"]


def test_new_sellers_have_distinct_ports_and_seeds():
    assert common.SELLER_PORTS["seller_4"] == 8014 and common.SELLER_PORTS["seller_5"] == 8015
    assert len(set(common.SELLER_PORTS.values())) == len(common.SELLER_PORTS)
    assert common.address("seller_4") != common.address("seller_5")


def test_pick_port_uses_config_port_else_next_free_from_8016():
    cfg = good()
    assert factory.pick_port(dict(cfg, port=9123)) == 9123
    p = factory.pick_port(cfg, start=8016)
    assert 8016 <= p < 8100 and p not in common.SELLER_PORTS.values()


def test_seller_agent_builds_a_custom_seller_from_a_config(monkeypatch):
    from unittest.mock import Mock, patch
    import seller_agent
    monkeypatch.delenv("AGENTS_MAILBOX", raising=False)
    monkeypatch.delenv("SELLERS_MAILBOX", raising=False)
    fake = Mock()
    fake.on_message.side_effect = lambda *a, **k: lambda fn: fn
    cfg = validate_config(dict(good(), port=9123))
    with patch.object(seller_agent, "Agent", return_value=fake) as ctor, patch.object(common, "include_profile_chat"):
        seller_agent.build(cfg["id"], cfg)
    kwargs = ctor.call_args.kwargs
    assert kwargs["port"] == 9123 and kwargs["name"] == "Corner PC" and kwargs["seed"] == common.SEEDS["corner-pc"]
    assert "readme_path" not in kwargs and "SIM" in kwargs["description"]


def test_seller_agent_build_refuses_seller_hyphen_1_and_never_signs_as_seller_1(monkeypatch):
    """The reviewer's repro: SELLER_1_AGENT_SEED set, id 'seller-1' must not build an agent with seller_1's address."""
    from unittest.mock import Mock, patch
    import seller_agent
    monkeypatch.setenv("SELLER_1_AGENT_SEED", "reviewer-fake-seed-xyz")
    before = dict(common.SEEDS)
    with patch.object(seller_agent, "Agent", return_value=Mock()) as ctor:
        with pytest.raises(ConfigError, match="reserved"):
            seller_agent.build("seller-1", dict(good(), id="seller-1", port=9124))
    ctor.assert_not_called()
    assert "seller-1" not in common.SEEDS and common.SEEDS == before


def test_seller_agent_cli_refuses_a_bad_config_with_the_field_names(tmp_path):
    import subprocess
    bad = good()
    bad["listings"][GPU_TI]["floor_by_condition"]["new"] = -3
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad))
    run = subprocess.run([sys.executable, str(Path(__file__).with_name("seller_agent.py")), "--config", str(p)],
                         capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert run.returncode != 0
    assert f"listings.{GPU_TI}.floor_by_condition.new" in run.stderr



def test_the_live_roster_is_four_sellers_with_four_distinct_jobs():  # #398
    run = [n for n in [*common.CATALOG_SELLERS, *common.MIRROR_SELLERS] if n not in common.RETIRED_SELLERS]
    assert run == ["seller_1", "seller_3", "seller_5", "seller_6"]
    assert set(common.SELLER_JOBS) == set(run) and len(set(common.SELLER_JOBS.values())) == 4
    assert set(common.RETIRED_SELLERS) == {"seller_2", "seller_4"} and all("same job as" in v for v in common.RETIRED_SELLERS.values())
    for n in run:   # each kept seller's Agentverse README states its one job right under the title
        assert (Path(__file__).parent / f"AGENTVERSE-{n}.md").read_text().split("\n")[2].startswith("**Job:")


def test_the_buyer_never_asks_a_retired_seller(monkeypatch):
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())   # an earlier asyncio.run closed the loop; uagents needs a current one
    import buyer.buyer_agent as B
    monkeypatch.setattr(common, "mailbox_ready", lambda s: True)
    assert not set(B.live_sellers()) & set(common.RETIRED_SELLERS)
