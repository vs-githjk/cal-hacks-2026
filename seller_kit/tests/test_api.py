"""Seller Kit API tests: a temp custom dir and fake need sources only, no network, no agents started.
Run: python3 -m pytest seller_kit -q"""
import copy
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents" / "sellers"))

from factory import load_config  # noqa: E402
from seller_kit import api  # noqa: E402

GPU = "rtx 5070 ti"


def good(**over):
    cfg = {
        "id": "corner-pc", "name": "Corner PC", "owner": "Sam", "archetype": "local shop", "origin": "SIM",
        "pricing": {"mode": "discount", "discount": 0.05}, "perks": ["30-day returns"], "claims": ["new, sealed"],
        "listings": {GPU: {
            "price": 1300.0, "floor_by_condition": {"new": 1200.0}, "condition": "new",
            "listing_url": "https://example.com/sim/corner-pc/rtx-5070-ti",
            "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti"}}},
    }
    cfg.update(over)
    return cfg


@pytest.fixture
def custom(tmp_path):
    return tmp_path / "custom"


@pytest.fixture
def client(custom):
    return TestClient(api.create_app(custom_dir=custom))


def fields(resp):
    return {e["field"]: e["message"] for e in resp.json()["errors"]}


# ---- POST /v1/sellers

def test_valid_config_is_written_and_returns_id_path_and_run_command(client, custom):
    r = client.post("/v1/sellers", json=good())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "corner-pc"
    assert body["config_path"] == str(custom / "corner-pc.json")
    assert "seller_agent.py --config" in body["run_command"] and body["config_path"] in body["run_command"]
    assert body["origin"] == "SIM"
    # what was written is a config the agent itself accepts
    assert load_config(body["config_path"])["name"] == "Corner PC"


def test_default_custom_dir_is_agents_sellers_custom():
    assert api.CUSTOM_DIR == REPO / "agents" / "sellers" / "custom"
    assert "agents/sellers/custom/" in (REPO / ".gitignore").read_text()


@pytest.mark.parametrize("mutate,field", [
    (lambda c: c["listings"][GPU]["floor_by_condition"].update(new=-5), "listings.rtx 5070 ti.floor_by_condition.new"),
    (lambda c: c["listings"][GPU]["floor_by_condition"].update(new=1400.0), "listings.rtx 5070 ti.floor_by_condition.new"),
    (lambda c: c["listings"][GPU].update(condition="mint"), "listings.rtx 5070 ti.condition"),
    (lambda c: c["listings"][GPU].update(listing_url="javascript:alert(1)"), "listings.rtx 5070 ti.listing_url"),
    (lambda c: c.update(name=""), "name"),
])
def test_bad_configs_get_422_with_field_errors_and_write_nothing(client, custom, mutate, field):
    cfg = good()
    mutate(cfg)
    r = client.post("/v1/sellers", json=cfg)
    assert r.status_code == 422
    assert field in fields(r), r.json()
    assert not custom.exists() or not list(custom.iterdir())


def test_every_error_is_listed_not_just_the_first(client):
    cfg = good()
    cfg["listings"][GPU]["floor_by_condition"]["new"] = -1
    cfg["listings"][GPU]["listing_url"] = "ftp://x.example/a"
    cfg["name"] = ""
    assert len(client.post("/v1/sellers", json=cfg).json()["errors"]) >= 3


@pytest.mark.parametrize("bad_id", ["../evil", "..", "a/b", "a\\b", "/etc/passwd", "x", "Corner", "corner pc", "a" * 41, "corner-pc.json"])
def test_path_traversal_and_odd_ids_are_refused(client, custom, tmp_path, bad_id):
    r = client.post("/v1/sellers", json=good(id=bad_id))
    assert r.status_code == 422 and "id" in fields(r)
    assert not [p for p in tmp_path.rglob("*.json")]


def test_reserved_ids_are_refused(client):
    for rid in ("seller_1", "seller-1", "buyer", "shield_agent"):
        assert client.post("/v1/sellers", json=good(id=rid)).status_code == 422


def test_origin_live_is_refused_the_kit_cannot_verify_a_shop(client):
    r = client.post("/v1/sellers", json=good(origin="LIVE"))
    assert r.status_code == 422 and "origin" in fields(r)


def test_body_that_is_not_a_json_object_gets_422_in_the_same_shape(client):
    for raw in ('[1,2]', '"x"', 'not json', ''):
        r = client.post("/v1/sellers", content=raw, headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "config", raw


def test_non_json_content_type_is_refused(client, custom):
    r = client.post("/v1/sellers", content=json.dumps(good()), headers={"content-type": "text/plain"})
    assert r.status_code in (415, 422)
    assert not custom.exists() or not list(custom.iterdir())


def test_oversized_body_gets_413(client, custom):
    big = good(perks=["x" * 100] * 10)
    big["pad"] = "y" * 70000
    r = client.post("/v1/sellers", content=json.dumps(big), headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert not custom.exists() or not list(custom.iterdir())


def test_same_id_twice_is_409_unless_replace(client, custom):
    assert client.post("/v1/sellers", json=good()).status_code == 201
    r = client.post("/v1/sellers", json=good(name="Other Shop"))
    assert r.status_code == 409 and "already" in r.json()["errors"][0]["message"]
    assert load_config(custom / "corner-pc.json")["name"] == "Corner PC"
    r = client.post("/v1/sellers?replace=true", json=good(name="Other Shop"))
    assert r.status_code == 201
    assert load_config(custom / "corner-pc.json")["name"] == "Other Shop"


def test_a_symlinked_config_is_never_followed(client, custom, tmp_path):
    custom.mkdir()
    target = tmp_path / "outside.json"
    target.write_text("keep")
    os.symlink(target, custom / "corner-pc.json")
    r = client.post("/v1/sellers?replace=true", json=good())
    assert r.status_code in (409, 422)
    assert target.read_text() == "keep"


def test_shop_limit(custom, monkeypatch):
    monkeypatch.setattr(api, "MAX_CUSTOM", 2)
    c = TestClient(api.create_app(custom_dir=custom))
    assert c.post("/v1/sellers", json=good(id="shop-aa")).status_code == 201
    assert c.post("/v1/sellers", json=good(id="shop-bb")).status_code == 201
    r = c.post("/v1/sellers", json=good(id="shop-cc"))
    assert r.status_code == 409 and "limit" in r.json()["errors"][0]["message"]


# ---- GET /v1/sellers

def test_list_is_empty_without_a_custom_dir(client):
    r = client.get("/v1/sellers")
    assert r.status_code == 200 and r.json() == []


def test_list_shows_written_shops_and_skips_broken_files(client, custom):
    client.post("/v1/sellers", json=good())
    (custom / "broken.json").write_text("{nope")
    (custom / "notes.txt").write_text("hi")
    rows = client.get("/v1/sellers").json()
    assert [r["id"] for r in rows] == ["corner-pc"]
    assert rows[0]["name"] == "Corner PC" and rows[0]["origin"] == "SIM" and rows[0]["skus"] == [GPU]
    assert rows[0]["config_path"] == str(custom / "corner-pc.json")


# ---- GET /v1/needs/open

def test_needs_fall_back_to_labelled_sim_samples(client):
    r = client.get("/v1/needs/open")
    assert r.status_code == 200
    needs = r.json()
    assert needs and all(n["origin"] == "SIM" for n in needs)
    for n in needs:
        assert n["sku_spec"] and n["allowed_conditions"] and n["quantity"] >= 1
        assert "spend_limit" not in n and "cap" not in n


def test_needs_come_from_the_source_function_and_unknown_origin_reads_sim(custom):
    rows = [{"id": "n1", "sku_spec": GPU, "allowed_conditions": ["new"], "quantity": 1, "origin": "MIRROR", "spend_limit": 900},
            {"id": "n2", "sku_spec": "psu 750w", "allowed_conditions": ["new"], "quantity": 2},
            {"id": "n3", "sku_spec": "ssd", "allowed_conditions": ["new"], "quantity": 1, "origin": "weird"}]
    c = TestClient(api.create_app(custom_dir=custom, needs_source=lambda: copy.deepcopy(rows)))
    got = {n["id"]: n for n in c.get("/v1/needs/open").json()}
    assert got["n1"]["origin"] == "MIRROR" and got["n2"]["origin"] == "SIM" and got["n3"]["origin"] == "SIM"
    assert all("spend_limit" not in n for n in got.values())


def test_a_failing_or_empty_source_falls_back_to_sim_and_never_500s(custom):
    def boom():
        raise RuntimeError("stdb down")
    for src in (boom, lambda: [], lambda: "garbage", lambda: [1, "x"]):
        c = TestClient(api.create_app(custom_dir=custom, needs_source=src))
        r = c.get("/v1/needs/open")
        assert r.status_code == 200 and r.json() and all(n["origin"] == "SIM" for n in r.json())


# ---- misc

def test_health_and_cors(client):
    assert client.get("/v1/health").json() == {"ok": True}
    ok = client.options("/v1/sellers", headers={"origin": "http://localhost:3100", "access-control-request-method": "POST",
                                                "access-control-request-headers": "content-type"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3100"
    bad = client.options("/v1/sellers", headers={"origin": "https://evil.example", "access-control-request-method": "POST",
                                                 "access-control-request-headers": "content-type"})
    assert "access-control-allow-origin" not in bad.headers
