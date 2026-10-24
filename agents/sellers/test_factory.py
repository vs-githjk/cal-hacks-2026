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


def test_all_five_sellers_validate_against_the_schema():
    schema = json.loads(SCHEMA.read_text())
    sellers = CATALOG["sellers"]
    assert sorted(sellers) == [f"seller_{i}" for i in range(1, 6)]
    for sid, entry in sellers.items():
        cfg = {"id": sid, **entry}
        Draft202012Validator(schema).validate(cfg)
        validate_config(cfg)
        assert cfg["origin"] == "SIM"
    assert common.SELLERS == [f"seller_{i}" for i in range(1, 6)]


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
