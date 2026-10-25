"""Real MIRROR listings and maker specs for the Build Story parts (#342). Fakes only: no network, no token, no spend."""
import json
import re
import sys
from pathlib import Path

import pytest

from data.fit_checker import build_check, part_specs
from data.mirror import normalize, parts, red_line, run_actors

ROWS = {
    "cpu": [
        {"brand": "AMD", "model_number": "100-100001404WOF", "match": r"\bryzen 7 9700x\b", "exclude": r"9700x3d", "socket": "AM5",
         "tdp_w": 65, "arch": "Zen 5", "source": "https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-7-9700x.html",
         "checked": "2026-10-24"},
        {"brand": "Intel", "model_number": "BX8071514600K", "match": r"\bi5-14600k\b", "exclude": r"14600kf", "socket": "LGA1700",
         "tdp_w": 125, "arch": "Raptor Lake", "source": "https://www.intel.com/content/www/us/en/products/sku/236773/", "checked": "2026-10-24"},
    ],
    "motherboard": [
        {"brand": "MSI", "model_number": "PRO B650-S WIFI", "match": r"\bpro b650-s wifi\b", "socket": "AM5", "memory_type": "DDR5",
         "memory_form": "DIMM", "memory_slots": 4, "form_factor": "ATX", "m2_slots": 2,
         "source": "https://www.msi.com/Motherboard/PRO-B650-S-WIFI/Specification", "checked": "2026-10-24"},
        {"brand": "MSI", "model_number": "PRO B760M-P DDR4", "match": r"\bpro b760m-p ddr4\b", "socket": "LGA1700", "memory_type": "DDR4",
         "memory_form": "DIMM", "memory_slots": 2, "form_factor": "Micro ATX", "m2_slots": 2,
         "source": "https://www.msi.com/Motherboard/PRO-B760M-P-DDR4/Specification", "checked": "2026-10-24"},
    ],
    "memory": [
        {"brand": "Corsair", "model_number": "CMK32GX5M2B6000C30", "match": r"cmk32gx5m2b6000c30", "memory_type": "DDR5", "speed_mhz": 6000,
         "modules": 2, "form": "DIMM", "source": "https://www.corsair.com/us/en/p/memory/cmk32gx5m2b6000c30", "checked": "2026-10-24"},
        {"brand": "Corsair", "model_number": "CMK32GX4M2E3200C16", "match": r"cmk32gx4m2e3200c16", "memory_type": "DDR4", "speed_mhz": 3200,
         "modules": 2, "form": "DIMM", "source": "https://www.corsair.com/us/en/p/memory/cmk32gx4m2e3200c16", "checked": "2026-10-24"},
    ],
    "storage": [
        {"brand": "WD", "model_number": "WDS100T3X0E", "match": r"\bsn770\b.*\b1tb\b", "interface": "NVMe", "form": "M.2",
         "source": "https://www.westerndigital.com/products/internal-drives/wd-black-sn770-nvme-ssd", "checked": "2026-10-24"},
    ],
    "cooler": [
        {"brand": "Thermalright", "model_number": "PA120SE", "match": r"peerless assassin 120 se", "height_mm": 155,
         "sockets": ["AM4", "AM5", "LGA1700"], "source": "https://www.thermalright.com/product/peerless-assassin-120-se/", "checked": "2026-10-24"},
    ],
}


@pytest.fixture
def specs(tmp_path, monkeypatch):
    f = tmp_path / "part_specs.json"
    f.write_text(json.dumps(ROWS))
    monkeypatch.setattr(part_specs, "DATA", f)
    return f


def item(title, price, url, model=None, **extra):
    return {"title": title, "price": price, "url": url, **({"modelNumber": model} if model else {}), **extra}


def card(store, part, title, price, url, model=None, snap="s-20261024T2200Z", **extra):
    return normalize.to_spec_card(store, item(title, price, url, model, **extra), snap, "2026-10-24T22:00:00+00:00", part=part)


# ---- maker rows: exact model only -------------------------------------------------------------------------------------
def test_an_exact_model_number_finds_its_row(specs):
    assert part_specs.find("cpu", "100-100001404wof", "anything")["socket"] == "AM5"


def test_a_strict_title_rule_finds_the_row_and_excludes_the_x3d(specs):
    assert part_specs.find("cpu", None, "AMD Ryzen 7 9700X Desktop Processor")["socket"] == "AM5"
    assert part_specs.find("cpu", None, "AMD Ryzen 7 9700X3D Desktop Processor") is None


@pytest.mark.parametrize("title", ["Ryzen 7 9700X + MSI B650 combo", "Ryzen 7 9700X gaming PC desktop", "Ryzen 7 9700X bundle"])
def test_a_bundle_or_prebuilt_is_never_the_bare_part(specs, title):
    assert part_specs.find("cpu", None, title) is None


def test_an_unknown_model_or_category_has_no_row(specs):
    assert part_specs.find("cpu", "NOPE", "AMD Ryzen 5 7600") is None
    assert part_specs.find("gpu", None, "RTX 5070 Ti") is None
    assert part_specs.find("cpu", None, None) is None


def test_a_missing_or_bad_file_means_no_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(part_specs, "DATA", tmp_path / "nope.json")
    assert part_specs.find("cpu", None, "AMD Ryzen 7 9700X") is None


def test_specs_cite_the_maker_page_and_the_date(specs):
    got = part_specs.maker("cpu", "AMD Ryzen 7 9700X")
    assert got["socket"][0] == "AM5" and "amd.com" in got["socket"][1] and "checked 2026-10-24" in got["socket"][1]
    assert got["microarchitecture"][0] == "Zen 5"


def test_the_shipped_rows_are_maker_domain_only_and_dated():
    data = json.loads(Path(part_specs.__file__).with_name("part_specs.json").read_text())
    for cat in part_specs.CATEGORIES:
        for r in data[cat]:
            assert re.match(r"https://[^/]+/", r["source"]) and re.fullmatch(r"20\d\d-\d\d-\d\d", r["checked"]), r
            assert not re.search(r"newegg|amazon|bestbuy|microcenter|pcpartpicker|techpowerup|wikipedia", r["source"]), r


# ---- category-aware cards ---------------------------------------------------------------------------------------------
def test_a_part_card_takes_its_attrs_from_the_maker_row_not_the_listing(specs):
    c = card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 299.99, "https://x/9700x", socket="LGA1851")
    assert c["category"] == "cpu" and c["maker_model"] == "100-100001404WOF"
    assert c["attrs"] == {"socket": "AM5", "tdp_w": 65, "microarchitecture": "Zen 5"} and c["origin"] == "MIRROR"


def test_an_unknown_model_card_has_no_maker_model_and_no_attrs(specs):
    c = card("bestbuy", "cpu", "AMD Ryzen 5 7600X", 199.0, "https://x/7600x")
    assert c["maker_model"] is None and c["attrs"] == {} and c["category"] == "cpu"


def test_the_gpu_path_is_unchanged_without_a_part():
    c = normalize.to_spec_card("bestbuy", item("MSI GeForce RTX 5070 Ti 16GB", 1000, "https://x/g"), "s", "d")
    assert c["category"] == "gpu" and "maker_model" not in c


# ---- offers: #344's shape ---------------------------------------------------------------------------------------------
def write(root, name, cards):
    root.mkdir(exist_ok=True)
    (root / f"{name}.json").write_text(json.dumps(cards))


@pytest.fixture
def snaps(tmp_path, specs):
    root = tmp_path / "parts_snapshots"
    write(root, "bestbuy-cpu-ryzen-7-9700x-20261024T2200Z", [
        card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 299.99, "https://bb/9700x"),
        card("bestbuy", "cpu", "AMD Ryzen 5 7600X", 199.0, "https://bb/7600x"),           # no maker row
        card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 0, "https://bb/free")])             # no usable price
    write(root, "microcenter-cpu-ryzen-7-9700x-20261024T2200Z", [
        card("microcenter", "cpu", "AMD Ryzen 7 9700X Processor", 289.99, "https://mc/9700x", model="100-100001404WOF")])
    write(root, "ebay_sold-cpu-ryzen-7-9700x-20261024T2200Z", [card("ebay_sold", "cpu", "AMD Ryzen 7 9700X", 150, "https://ebay/1")])
    write(root, "amazon-cpu-ryzen-7-9700x-20261024T2200Z", [
        card("amazon", "cpu", "AMD Ryzen 7 9700X", 280.0, "https://amz/1", seller="SomeShop LLC"),
        card("amazon", "cpu", "AMD Ryzen 7 9700X", 295.0, "https://amz/2", seller="Amazon.com")])
    return root


def test_offers_have_the_344_shape_cheapest_first(snaps):
    got = parts.offers("cpu", root=snaps)
    assert [o["seller"] for o in got] == ["Micro Center", "Amazon", "Best Buy"]
    o = got[0]
    assert o["price_cents"] == 28999 and o["source"] == "https://mc/9700x" and o["origin"] == "MIRROR"
    assert o["spec"]["name"] == "AMD Ryzen 7 9700X Processor" and o["spec"]["socket"] == "AM5" and o["spec"]["model_number"] == "100-100001404WOF"
    assert o["snapshot_id"] and o["captured_at"] and o["condition"] == "unknown" and o["orderable"] is True
    assert o["maker_source"].startswith("https://www.amd.com") and o["maker_checked"] == "2026-10-24"


def test_an_unknown_model_never_bids_and_every_skip_has_a_reason(snaps):
    assert all("7600" not in o["spec"]["name"] for o in parts.offers("cpu", root=snaps))
    why = {s["title"]: s["reason"] for s in parts.skipped("cpu", root=snaps)}
    assert "no maker spec row" in why["AMD Ryzen 5 7600X"]


def test_sold_history_and_third_party_amazon_sellers_never_bid(snaps):
    got = parts.offers("cpu", root=snaps)
    assert not any("ebay" in str(o["source"]) or o["source"] == "https://amz/1" for o in got)
    reasons = " ".join(s["reason"] for s in parts.skipped("cpu", root=snaps))
    assert "baseline only" in reasons and "not Amazon itself" in reasons


def test_central_computers_rows_are_never_orderable(tmp_path, specs):
    root = tmp_path / "p"
    write(root, "centralcomputers-cpu-category-page-20261024T2200Z", [
        {**card("centralcomputers", "cpu", "AMD Ryzen 7 9700X", 279.99, "https://cc/9700x"), "listing": {"price": 279.99, "availability": "in_stock_sf_store", "url": "https://cc/9700x"}}])
    got = parts.offers("cpu", root=root)
    assert len(got) == 1 and got[0]["orderable"] is False and got[0]["seller"] == "Central Computers (SF)"


def test_condition_is_unknown_unless_the_page_states_it(tmp_path, specs):
    root = tmp_path / "p"
    write(root, "bestbuy-cpu-x-20261024T2200Z", [card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 299.0, "https://a", condition="Open-Box Excellent"),
                                                  card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 301.0, "https://b")])
    assert [o["condition"] for o in parts.offers("cpu", root=root)] == ["open-box", "unknown"]


def test_only_the_newest_snapshot_of_a_search_counts(tmp_path, specs):
    root = tmp_path / "p"
    write(root, "bestbuy-cpu-x-20261024T1000Z", [card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 250.0, "https://old")])
    write(root, "bestbuy-cpu-x-20261024T2200Z", [card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 299.0, "https://new")])
    assert [o["source"] for o in parts.offers("cpu", root=root)] == ["https://new"]


def test_owned_parts_get_no_offers_and_the_budget_ceiling_filters(snaps):
    assert parts.offers("cpu", owned={"cpu": {"name": "mine"}}, root=snaps) == []
    assert [o["seller"] for o in parts.offers("cpu", max_price_cents=29000, root=snaps)] == ["Micro Center"]
    assert parts.offers("gpu", root=snaps) == []


def test_out_of_stock_listings_do_not_bid(tmp_path, specs):
    root = tmp_path / "p"
    c = card("bestbuy", "cpu", "AMD Ryzen 7 9700X", 299.0, "https://a")
    c["listing"]["availability"] = "out of stock"
    write(root, "bestbuy-cpu-x-20261024T2200Z", [c])
    assert parts.offers("cpu", root=root) == []


# ---- the search list and the Actor inputs -----------------------------------------------------------------------------
def test_the_search_list_covers_every_part_with_the_design_queries():
    by = {}
    for s in parts.PART_SEARCHES:
        by.setdefault(s["part"], []).append(s["query"])
    assert set(by) == set(parts.PARTS) and "Ryzen 7 9700X" in by["cpu"] and "DDR4 32GB 3200" in by["memory"]
    assert "Thermalright Peerless Assassin 120 SE" in by["cooler"] and all(s["slug"] for s in parts.PART_SEARCHES)


def test_every_planned_run_has_a_real_actor_and_the_query_in_its_input():
    plan = parts.planned_runs(5)
    assert len(plan) == len(parts.PART_SEARCHES) * 7
    for r in plan:
        assert r["actor"] and "Ryzen" not in "" and json.dumps(r["input"]).lower().replace("%20", " ").replace("+", " ").count(
            r["query"].lower().split()[0]) >= 1


# ---- the capture: cap, SPEND, dry run ---------------------------------------------------------------------------------
class FakeApi:
    def __init__(self, cost=0.05, fail=None):
        self.calls, self.cost, self.fail = [], cost, fail

    def __call__(self, method, path, body=None, timeout=330):
        self.calls.append((method, path))
        if method == "POST" and "/runs" in path:
            if self.fail and self.fail in path:
                raise OSError("boom")
            return {"data": {"id": "r1", "status": "SUCCEEDED", "usageTotalUsd": self.cost, "defaultDatasetId": "d1"}}
        if "/datasets/" in path:
            return [{"title": "AMD Ryzen 7 9700X", "price": 299.99, "url": "https://x/1"}]
        raise AssertionError(path)


@pytest.fixture
def sandbox(tmp_path, specs, monkeypatch):
    monkeypatch.setattr(parts, "SNAPSHOTS", tmp_path / "parts_snapshots")
    monkeypatch.setattr(parts, "RAW", tmp_path / "raw")
    monkeypatch.setattr(run_actors, "HERE", tmp_path)
    (tmp_path / "runs.json").write_text(json.dumps([{"actor": parts.actor_for("microcenter"), "cost_usd": 0.09}]))
    monkeypatch.setattr(run_actors.time, "sleep", lambda s: None)
    return tmp_path


def test_a_dry_run_prints_the_estimate_and_makes_no_call(sandbox):
    api, lines = FakeApi(), []
    assert run_actors.parts_main(["--dry-run"], api=api, out=lines.append, ask=lambda p: pytest.fail("no prompt on a dry run")) == 0
    assert api.calls == [] and any(l.startswith("estimated Apify cost: $") for l in lines) and "nothing was spent" in lines[-1]


def test_the_estimate_uses_the_highest_logged_cost_per_actor(sandbox):
    plan = run_actors.parts_plan(5, ["cpu"])
    mc = [r for r in plan if r["actor"] == parts.actor_for("microcenter")]
    assert mc and all(r["worst_usd"] == 0.09 for r in mc)
    assert all(r["worst_usd"] == run_actors.UNLOGGED_USD for r in plan if r["actor"] == parts.actor_for("amazon"))


def test_the_spend_prompt_cannot_be_skipped(sandbox):
    api, lines = FakeApi(), []
    for answer in ("", "yes", "spend", "SPEND please"):
        assert run_actors.parts_main(["--parts", "cpu"], api=api, out=lines.append, ask=lambda p, a=answer: a) == 2
    assert api.calls == []
    with pytest.raises(SystemExit):   # no flag skips the prompt
        for flag in ("--yes", "-y", "--no-confirm", "--force"):
            run_actors.parts_main(["--parts", "cpu", flag], api=api, ask=lambda p: "SPEND")


def test_typing_spend_runs_writes_snapshots_and_logs_cost_and_approval(sandbox):
    api = FakeApi(cost=0.01)
    assert run_actors.parts_main(["--parts", "cpu", "--cap", "5", "--approved-by", "Anoop in chat 17:20 PDT"], api=api,
                                 ask=lambda p: "SPEND", out=lambda l: None, workers=1) == 0
    log = json.loads((sandbox / "runs.json").read_text())[1:]
    assert len(log) == 3 * 7 + 1 and all(r["cost_usd"] == 0.01 and "Anoop in chat 17:20 PDT; cap $5.00" == r["approval"] for r in log)
    files = list((sandbox / "parts_snapshots").glob("*.json"))
    assert len(files) == 22 and all(re.search(r"-\d{8}T\d{4}Z\.json$", f.name) for f in files)
    cards = json.loads(next(f for f in files if not f.name.startswith('centralcomputers')).read_text())
    assert cards[0]["category"] == "cpu" and cards[0]["maker_model"]


def test_the_cap_stops_before_overspend_and_skips_the_rest(sandbox):
    plan = run_actors.parts_plan(5, ["cpu"])
    recs = run_actors.run_parts(plan, 0.12, api=FakeApi(cost=0.05), workers=1)
    started = [r for r in recs if r["status"] != "SKIPPED"]
    assert 0 < len(started) < len(plan)
    assert sum(r["cost_usd"] for r in started) <= 0.12 and all("would be passed" in r["error"] for r in recs if r["status"] == "SKIPPED")


def test_an_unknown_cost_is_charged_at_its_worst_case(sandbox):
    api = FakeApi(cost=None)
    recs = run_actors.run_parts(run_actors.parts_plan(5, ["cpu"]), 0.25, api=api, workers=1)
    assert any(r["status"] == "SKIPPED" for r in recs)


def test_the_cap_is_at_most_ten_dollars_and_an_estimate_over_the_cap_is_refused(sandbox):
    api, lines = FakeApi(), []
    assert run_actors.parts_main(["--cap", "11"], api=api, out=lines.append, ask=lambda p: "SPEND") == 2
    assert run_actors.parts_main(["--cap", "0.01"], api=api, out=lines.append, ask=lambda p: "SPEND") == 2
    assert api.calls == [] and any("over the cap" in l for l in lines)


def test_one_broken_run_is_logged_and_the_others_still_land(sandbox):
    api = FakeApi(fail="bestbuy-scraper")
    recs = run_actors.run_parts(run_actors.parts_plan(5, ["cpu"]), 5, api=api, workers=1)
    bad = [r for r in recs if str(r["status"]).startswith("ERROR")]
    assert bad and len(bad) < len(recs) and any(r["status"] == "SUCCEEDED" for r in recs)


def test_no_token_or_dash_ever_lands_in_the_log(sandbox):
    run_actors.parts_main(["--parts", "cpu", "--approved-by", "Anoop"], api=FakeApi(), ask=lambda p: "SPEND", out=lambda l: None, workers=1)
    text = (sandbox / "runs.json").read_text()
    assert "apify_api_" not in text and "Bearer" not in text


# ---- the fit checker reads the maker rows -----------------------------------------------------------------------------
def test_check_build_fills_a_named_cpu_and_board_from_the_maker_rows_and_cites_them(specs):
    out = build_check.check_build({"cpu": "AMD Ryzen 7 9700X", "motherboard": "MSI PRO B650-S WIFI"})
    c = next(c for c in out["checks"] if c["rule_id"] == "fit.cpu_socket")
    assert c["verdict"] == "pass" and any("amd.com" in s for s in c["sources"]) and any("msi.com" in s for s in c["sources"])


def test_a_real_socket_clash_between_two_picks_fails(specs):
    out = build_check.check_build({"cpu": "AMD Ryzen 7 9700X", "motherboard": "MSI PRO B760M-P DDR4"})
    assert next(c for c in out["checks"] if c["rule_id"] == "fit.cpu_socket")["verdict"] == "fail"


def test_the_ram_generation_clash_fails(specs):
    out = build_check.check_build({"motherboard": "MSI PRO B650-S WIFI", "memory": "Corsair Vengeance CMK32GX4M2E3200C16 32GB DDR4"})
    assert next(c for c in out["checks"] if c["rule_id"] == "fit.ram_type")["verdict"] == "fail"


def test_an_unknown_cpu_is_uncertain_never_guessed(specs):
    out = build_check.check_build({"cpu": "AMD Ryzen 5 7600X", "motherboard": "MSI PRO B650-S WIFI"})
    assert next(c for c in out["checks"] if c["rule_id"] == "fit.cpu_socket")["verdict"] == "uncertain"


def test_the_callers_own_spec_beats_the_maker_row(specs):
    out = build_check.check_build({"cpu": {"name": "AMD Ryzen 7 9700X", "socket": "LGA1700"}, "motherboard": "MSI PRO B760M-P DDR4"})
    assert next(c for c in out["checks"] if c["rule_id"] == "fit.cpu_socket")["verdict"] == "pass"


def test_a_cooler_row_gives_height_and_sockets(specs):
    got = part_specs.maker("cooler", "Thermalright Peerless Assassin 120 SE Black")
    assert got["height_mm"][0] == 155 and "AM5" in got["sockets"][0]


# ---- the real red line ------------------------------------------------------------------------------------------------
def offer(part, seller, cents, title, **spec):
    return {"seller": seller, "price_cents": cents, "spec": {"name": title, **spec}, "source": f"https://x/{title}", "origin": "MIRROR"}


def test_the_red_line_finds_a_cpu_board_socket_clash_and_the_swap(specs):
    offers = {"cpu": [offer("cpu", "Best Buy", 28999, "AMD Ryzen 7 9700X")],
              "motherboard": [offer("motherboard", "Micro Center", 9999, "MSI PRO B760M-P DDR4"),
                              offer("motherboard", "Best Buy", 15999, "MSI PRO B650-S WIFI")]}
    res = red_line.find(offers)
    assert res["verdict"] == "red-swap-green" and res["clash"]["rule_id"] == "fit.cpu_socket"
    assert res["clash"]["part"] == "motherboard" and "B760M" in res["clash"]["title"]
    assert res["swap"]["title"] == "MSI PRO B650-S WIFI" and res["swap"]["price_cents"] == 15999


def test_no_clash_means_no_real_red_line(specs):
    offers = {"cpu": [offer("cpu", "Best Buy", 28999, "AMD Ryzen 7 9700X")],
              "motherboard": [offer("motherboard", "Best Buy", 15999, "MSI PRO B650-S WIFI")]}
    assert red_line.find(offers)["verdict"] == "none"


def test_a_ram_type_clash_is_found_when_the_sockets_agree(specs):
    offers = {"motherboard": [offer("motherboard", "Best Buy", 15999, "MSI PRO B650-S WIFI")],
              "memory": [offer("memory", "Micro Center", 5999, "Corsair CMK32GX4M2E3200C16 DDR4"),
                         offer("memory", "Best Buy", 9999, "Corsair CMK32GX5M2B6000C30 DDR5")]}
    res = red_line.find(offers)
    assert res["verdict"] == "red-swap-green" and res["clash"]["rule_id"] == "fit.ram_type"


def test_over_budget_offers_are_not_tried(specs):
    offers = {"cpu": [offer("cpu", "Best Buy", 99999, "AMD Ryzen 7 9700X")]}
    res = red_line.find(offers)
    assert res["verdict"] == "blocked" and res["blocked_part"] == "cpu" and res["picks"] == {}


def test_a_pick_may_pass_its_share_when_the_open_parts_can_be_covered(specs):
    offers = {"cpu": [offer("cpu", "Best Buy", 28999, "AMD Ryzen 7 9700X")],
              "motherboard": [offer("motherboard", "Best Buy", 15999, "MSI PRO B650-S WIFI")]}
    assert red_line.find(offers)["picks"]["cpu"]["price_cents"] == 28999


def test_the_red_line_report_has_no_dashes(specs):
    offers = {"cpu": [offer("cpu", "Best Buy", 28999, "AMD Ryzen 7 9700X")],
              "motherboard": [offer("motherboard", "Micro Center", 9999, "MSI PRO B760M-P DDR4"), offer("motherboard", "Best Buy", 15999, "MSI PRO B650-S WIFI")]}
    text = "\n".join(red_line.report(red_line.find(offers)))
    assert "–" not in text and "—" not in text and "RED" in text


# ---- Central Computers category pages --------------------------------------------------------------------------------
from data.mirror import central_parts   # noqa: E402

CENTRAL_SAMPLE = (Path(__file__).parent / "fixtures" / "central_parts_cooler_sample.md").read_text()


def test_a_central_computers_page_parses_title_link_model_sku_stock_and_price():
    got = [central_parts.parse_entry(b) for b in central_parts.entries(CENTRAL_SAMPLE)]
    assert len(got) == 3 and all(got)
    assert got[0]["price"] == 99.99 and got[0]["sku"] == "CPUZZZNOC49R" and got[0]["model"] == "NH-D9 AMP-4926 4U"
    assert got[0]["sf_store_qty"] == 0 and got[1]["sf_store_qty"] == 1 and len(got[0]["store_inventory"]) == 5
    assert got[0]["url"].startswith("https://www.centralcomputer.com/") and got[0]["url"].endswith(".html")


def test_a_sale_line_reads_the_special_price():
    assert [central_parts.parse_entry(b)["price"] for b in central_parts.entries(CENTRAL_SAMPLE)][2] == 19.99


def test_central_cards_say_in_stock_only_when_the_sf_store_has_one_and_never_state_a_condition(specs):
    cards = central_parts.cards("cooler", [{"url": "https://www.centralcomputer.com/x.html", "markdown": CENTRAL_SAMPLE}], "s", "2026-10-25T01:24:00+00:00")
    assert [c["listing"]["availability"] for c in cards] == ["not_in_sf_store", "in_stock_sf_store", "in_stock_sf_store"]
    assert all(c["condition"] == "unknown" and c["origin"] == "MIRROR" and c["listing"]["seller"] == "Central Computers" for c in cards)
    assert cards[1]["listing"]["source_page"] == "https://www.centralcomputer.com/x.html" and cards[1]["listing"]["sf_store_qty"] == 1


def test_a_block_with_no_price_or_link_is_dropped_not_guessed():
    assert central_parts.parse_entry("1.   no product here\n   Model: X\n") is None
    assert central_parts.cards("cpu", [{"markdown": ""}, {}, None, "junk"], "s", "d") == []


def test_a_central_computers_listing_not_in_the_sf_store_never_bids(tmp_path, specs):
    root = tmp_path / "p"
    c = card("centralcomputers", "cooler", "Thermalright Peerless Assassin 120 SE CPU Air Cooler", 39.99, "https://cc/pa")
    c["listing"] = {"price": 39.99, "availability": "not_in_sf_store", "url": "https://cc/pa"}
    write(root, "centralcomputers-cooler-category-page-20261025T0124Z", [c])
    assert parts.offers("cooler", root=root) == []
    assert "not in stock" in parts.skipped("cooler", root=root)[0]["reason"]


def test_the_central_crawl_reads_one_page_and_the_stores_filter_and_workers_flags_work(sandbox):
    plan = run_actors.parts_plan(5, ["cpu"], stores=["centralcomputers"])
    assert [r["store"] for r in plan] == ["centralcomputers"] and plan[0]["input"]["maxCrawlPages"] == 1 and plan[0]["input"]["maxCrawlDepth"] == 0


def test_renormalize_rebuilds_cards_from_raw_with_the_current_maker_rows(tmp_path, specs):
    snaps, raw = tmp_path / "parts_snapshots", tmp_path / "raw"
    snaps.mkdir(); raw.mkdir()
    name = "bestbuy-cpu-ryzen-7-9700x-20261024T2200Z"
    (raw / f"{name}.json").write_text(json.dumps([item("AMD Ryzen 7 9700X", 299.99, "https://bb/9700x")]))
    (snaps / f"{name}.json").write_text(json.dumps([{"snapshot_date": "2026-10-24T22:00:00+00:00"}]))   # an old card with no maker model
    assert parts.renormalize(snaps, raw) == [name]
    c = json.loads((snaps / f"{name}.json").read_text())[0]
    assert c["maker_model"] == "100-100001404WOF" and c["snapshot_date"] == "2026-10-24T22:00:00+00:00" and c["price"] == 299.99


def test_an_amazon_listing_that_names_no_seller_never_bids(tmp_path, specs):
    root = tmp_path / "p"
    write(root, "amazon-cpu-x-20261024T2200Z", [card("amazon", "cpu", "AMD Ryzen 7 9700X", 280.0, "https://amz/none")])
    assert parts.offers("cpu", root=root) == []


@pytest.mark.parametrize("title,ok", [("Samsung - 990 PRO 2TB Internal SSD PCle Gen 4x4 NVMe", True),
                                      ("990 PRO 2TB Samsung V NAND 3-bit MLC PCIe Gen 4 x4 NVMe M.2 Internal SSD", True),
                                      ("Samsung SSD 990 PRO 2TB, PCIe 4.0 M.2 2280, Up to 7,450 MB/s", True),
                                      ("Samsung - 990 PRO 1TB Internal SSD PCle Gen 4x4 NVMe", False),
                                      ("Samsung Ark 2nd Gen 55in 4K Curved Monitor & 2TB 990 PRO M.2 SSD with Heatsink Kit", False),
                                      ("Samsung SSD 9100 PRO 2TB, PCIe 5.0x4 M.2 2280", False)])
def test_the_shipped_ssd_row_matches_only_the_990_pro_2tb(title, ok):  # #397 A2: the storage slot had no maker row
    row = part_specs.find("storage", None, title)
    assert (row is not None) is ok
    if ok:
        assert row["interface"] == "NVMe" and row["source"].startswith("https://www.samsung.com/") and row["checked"]
