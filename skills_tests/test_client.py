"""Tests for the tech-bazaar-seller skill: its client script and its packaging. A fake transport and a temp custom
folder only: no network, no agent started. Run: python3 -m pytest skills_tests -q"""
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / ".claude" / "skills" / "tech-bazaar-seller"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "agents" / "sellers"))

from seller_kit import api  # noqa: E402

spec = importlib.util.spec_from_file_location("seller_kit_client", SKILL_DIR / "seller_kit_client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

GPU = "rtx 5070 ti"


def answers(**over):
    a = {
        "store": "Corner PC", "owner": "Sam", "archetype": "local shop, fair prices",
        "pricing": {"mode": "fixed_margin", "margin_pct": 8},
        "returns": "30 days, no restocking fee", "perks": ["free local pickup"], "claims": ["new, sealed"],
        "items": [{"sku": "RTX  5070 Ti", "condition": "new", "cost": 1100, "floor": 1150,
                   "url": "https://example.com/sim/corner-pc/rtx-5070-ti",
                   "attrs": {"category": "gpu", "chipset": "RTX 5070 Ti"}}],
    }
    a.update(over)
    return a


class Recorder:
    """Fake transport: records every call and answers with the canned (status, payload), or raises."""

    def __init__(self, status=201, payload=None, raises=None):
        self.calls, self.status, self.payload, self.raises = [], status, payload, raises

    def __call__(self, method, url, body=None):
        self.calls.append((method, url, json.loads(body) if body else None))
        if self.raises:
            raise self.raises
        return self.status, self.payload


def real_api_transport(custom_dir):
    """Transport that talks to the real Seller Kit app in-process, so the built config meets the real guard."""
    tc = TestClient(api.create_app(custom_dir=custom_dir))

    def transport(method, url, body=None):
        path = urlsplit(url)
        r = tc.request(method, path.path + (f"?{path.query}" if path.query else ""), content=body,
                       headers={"content-type": "application/json"} if body else {})
        return r.status_code, r.json()
    return transport


# ---- build_config

def test_build_config_makes_a_sim_seller_config_from_owner_answers():
    cfg = client.build_config(answers())
    assert cfg["id"] == "corner-pc" and cfg["name"] == "Corner PC" and cfg["owner"] == "Sam"
    assert cfg["origin"] == "SIM"
    assert cfg["pricing"] == {"mode": "fixed_margin", "margin_pct": 8}
    listing = cfg["listings"][GPU]  # sku lowercased, spaces collapsed
    assert listing["cost"] == 1100 and "price" not in listing
    assert listing["floor_by_condition"] == {"new": 1150}
    assert listing["condition"] == "new" and listing["listing_url"] == "https://example.com/sim/corner-pc/rtx-5070-ti"
    assert listing["attrs"]["chipset"] == "RTX 5070 Ti"
    assert "30-day returns: 30 days, no restocking fee" in cfg["perks"] and "free local pickup" in cfg["perks"]
    assert cfg["claims"] == ["new, sealed"]


def market_returns_days(perks):
    """The market's own reading of return days: the regex is taken from market/rules/scoring.ts so a change there fails here."""
    src = (REPO / "market" / "rules" / "scoring.ts").read_text(encoding="utf-8")
    m = re.search(r"const returnsDays = .*?/(\(\\d\+\)[^/]*)/i\.exec", src)
    assert m, "returnsDays regex not found in scoring.ts"
    rx = re.compile(m.group(1), re.I)
    return max([0] + [int(g.group(1)) for p in perks if (g := rx.search(p))])


@pytest.mark.parametrize("returns,days", [
    ("30 days, no restocking fee", 30), ("14-day returns", 14), ("7 day money back", 7), ("30days", 30),
    ("no returns", 0), ("store credit only", 0), ("0 days", 0),
    ("90-day warranty, 14-day returns", 14), ("90-day warranty, 14 days returns", 14), ("90 day warranty, 14 days money back", 14),
    ("90-day warranty, 30 days to return", 30), ("90-day warranty only", 0), ("returns: 14-day returns", 14),
])
def test_a_returns_answer_with_a_day_count_reaches_the_market_as_N_day_returns(returns, days):
    cfg = client.build_config(answers(returns=returns, perks=["free local pickup"]))
    assert market_returns_days(cfg["perks"]) == days, cfg["perks"]
    assert any(returns in p for p in cfg["perks"]) and "free local pickup" in cfg["perks"]  # owner's wording kept
    assert len(cfg["perks"]) == 2  # one perk for the returns answer, never two


def test_a_warranty_day_count_never_becomes_a_returns_day_count():
    """The first day count is not always returns: '90-day warranty, 14-day returns' must stay 14 in the market's reading."""
    cfg = client.build_config(answers(returns="90-day warranty, 14-day returns"))
    assert market_returns_days(cfg["perks"]) == 14 and "90-day returns" not in cfg["perks"], cfg["perks"]


@pytest.mark.parametrize("returns", [
    "no returns, 90-day limited warranty",
    "No returns accepted. 2 year warranty, 60 days parts guarantee",
    "final sale, 30 days of free support",
])
def test_a_shop_with_no_returns_never_gets_a_public_N_day_returns_perk(returns):
    """A day count that belongs to a warranty, guarantee or support clause is not a returns policy (the market would
    read it as one and skip the 2 percent no-returns penalty)."""
    cfg = client.build_config(answers(returns=returns))
    assert market_returns_days(cfg["perks"]) == 0, cfg["perks"]
    assert not any(re.search(r"\d+-day returns", p) for p in cfg["perks"]), cfg["perks"]
    assert any(returns in p for p in cfg["perks"])  # the owner's words are still shown


@pytest.mark.parametrize("returns", [
    "no returns, 90-day limited warranty",
    "90-day manufacturer warranty",
    "90-day parts and labor warranty",
    "90 days parts and labor guarantee",
    "90-day limited warranty covers defects",
    "90-day warranty on all parts",
    "90-day limited warranty, no returns",
    "90-day mfr. warranty",
    "90-day ltd. warranty",
])
def test_a_warranty_or_guarantee_count_with_words_between_is_never_read_as_returns_days(returns):
    """Parked T3 finding: only 'warranty' right after the count was skipped, so any word in between ('limited',
    'manufacturer', 'parts and labor') let the market read '90-day returns' and drop the no-returns penalty."""
    cfg = client.build_config(answers(returns=returns))
    assert client._return_days(returns) == 0
    assert market_returns_days(cfg["perks"]) == 0, cfg["perks"]
    assert not any(re.search(r"\d+-day returns", p) for p in cfg["perks"]), cfg["perks"]
    assert any(returns in p for p in cfg["perks"])


def test_nine_perks_and_a_returns_answer_still_fit_the_ten_perk_limit():
    nine = [f"perk {i}" for i in range(9)]
    cfg = client.build_config(answers(returns="30 days", perks=nine))
    assert len(cfg["perks"]) == 10 and market_returns_days(cfg["perks"]) == 30


def test_a_returns_answer_too_long_to_fold_needs_two_slots_and_the_owner_is_told_how_many_perks_fit():
    long = "30 days, " + "no restocking fee and free return label " * 3
    assert len(long) > 106
    cfg = client.build_config(answers(returns=long, perks=["a"] * 8))
    assert len(cfg["perks"]) == 10 and market_returns_days(cfg["perks"]) == 30
    with pytest.raises(client.ClientError) as e:
        client.build_config(answers(returns=long, perks=["a"] * 9))
    assert "at most 8 other perks" in str(e.value) and "2 of the 10" in str(e.value)


def test_the_day_count_perk_is_not_added_twice_when_the_owner_already_gave_it():
    cfg = client.build_config(answers(returns="30 days", perks=["30-day returns"]))
    assert [p for p in cfg["perks"] if "30-day returns" in p.lower()] == ["30-day returns"]


def test_the_real_kit_keeps_the_day_count_perk_so_a_30_day_shop_is_not_penalised(tmp_path):
    custom = tmp_path / "custom"
    client.post_config(client.build_config(answers()), "http://127.0.0.1:8791", transport=real_api_transport(custom))
    written = json.loads((custom / "corner-pc.json").read_text(encoding="utf-8"))
    assert market_returns_days(written["perks"]) == 30


def test_two_items_with_the_same_part_are_refused_not_silently_merged():
    first = {"sku": "RTX 5070 Ti", "condition": "new", "cost": 1100, "floor": 1150, "url": "https://example.com/a"}
    second = {"sku": "rtx  5070 ti", "condition": "open-box", "cost": 900, "floor": 950, "url": "https://example.com/b"}
    with pytest.raises(client.ClientError) as e:
        client.build_config(answers(items=[first, second]))
    msg = str(e.value)
    assert "item 1" in msg and "item 2" in msg and "RTX 5070 Ti" in msg and "rtx  5070 ti" in msg
    assert "also" in msg and "floors" in msg


def test_the_cli_reports_a_repeated_part_as_bad_input_and_calls_nothing(tmp_path):
    item = answers()["items"][0]
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers(items=[item, dict(item, condition="open-box")])))
    rec, out, err = Recorder(), io.StringIO(), io.StringIO()
    code = client.main([str(f)], transport=rec, stdout=out, stderr=err)
    assert code == 1 and rec.calls == [] and "also" in err.getvalue() and "Traceback" not in err.getvalue()


def test_discount_percent_becomes_the_fraction_the_kit_reads():
    cfg = client.build_config(answers(pricing={"mode": "discount", "discount_pct": 5},
                                      items=[{"sku": "psu 750w", "condition": "new", "price": 99.99, "floor": 89,
                                              "url": "https://example.com/sim/psu"}]))
    assert cfg["pricing"] == {"mode": "discount", "discount": 0.05}
    assert cfg["listings"]["psu 750w"]["price"] == 99.99


def test_floors_per_condition_and_extra_condition_lines():
    item = {"sku": GPU, "condition": "new", "price": 1300, "floors": {"new": 1200, "open-box": 1050},
            "url": "https://example.com/a", "also": [{"condition": "open-box", "price": 1150}]}
    cfg = client.build_config(answers(pricing={"mode": "discount", "discount_pct": 0}, items=[item]))
    listing = cfg["listings"][GPU]
    assert listing["floor_by_condition"] == {"new": 1200, "open-box": 1050}
    assert listing["alt_lines"] == [{"condition": "open-box", "price": 1150}]


def test_values_are_not_fixed_up_so_the_kit_is_the_guard():
    """A bad floor, URL or condition goes to the API exactly as the owner gave it; the client never repairs it."""
    item = {"sku": GPU, "condition": "mint", "cost": 1100, "floor": -5, "url": "javascript:alert(1)"}
    cfg = client.build_config(answers(items=[item]))
    listing = cfg["listings"][GPU]
    assert listing["floor_by_condition"] == {"mint": -5}
    assert listing["listing_url"] == "javascript:alert(1)" and listing["condition"] == "mint"


def test_origin_is_always_sim_even_if_the_owner_asks_for_live():
    assert client.build_config(answers(origin="LIVE"))["origin"] == "SIM"


def test_store_name_becomes_the_id_unless_one_is_given():
    assert client.build_config(answers(store="Dave's PC & Parts!"))["id"] == "dave-s-pc-parts"
    assert client.build_config(answers(id="daves-pc"))["id"] == "daves-pc"


def test_missing_answers_are_left_out_so_the_kit_names_the_fields():
    cfg = client.build_config({"store": "X Shop"})
    assert cfg["name"] == "X Shop" and cfg["listings"] == {}


def test_a_non_object_answers_file_is_a_clear_error():
    with pytest.raises(client.ClientError, match="object"):
        client.build_config(["not", "an", "object"])


# ---- post_config

def test_post_sends_json_to_the_kit_and_returns_its_answer():
    reply = {"id": "corner-pc", "config_path": "/x/corner-pc.json", "run_command": "cd /x && run"}
    rec = Recorder(201, reply)
    out = client.post_config(client.build_config(answers()), "http://127.0.0.1:8791", transport=rec)
    assert out == reply
    method, url, body = rec.calls[0]
    assert (method, url) == ("POST", "http://127.0.0.1:8791/v1/sellers")
    assert body["id"] == "corner-pc"


def test_replace_flag_adds_the_query():
    rec = Recorder(201, {"id": "a", "config_path": "p", "run_command": "r"})
    client.post_config({"id": "a"}, "http://127.0.0.1:8791/", transport=rec, replace=True)
    assert rec.calls[0][1] == "http://127.0.0.1:8791/v1/sellers?replace=true"


def test_api_down_is_a_clear_refusal_not_a_traceback():
    rec = Recorder(raises=ConnectionRefusedError("refused"))
    with pytest.raises(client.KitDown) as e:
        client.post_config({"id": "a"}, "http://127.0.0.1:8791", transport=rec)
    msg = str(e.value)
    assert "not running" in msg and "http://127.0.0.1:8791" in msg and "Nothing was saved" in msg
    assert "scripts/launch.py up" in msg


def test_422_carries_every_field_error():
    errs = [{"field": "listings.rtx 5070 ti.floor_by_condition.new", "message": "floor is above price"},
            {"field": "name", "message": "must not be empty"}]
    with pytest.raises(client.KitRefused) as e:
        client.post_config({}, "http://k", transport=Recorder(422, {"errors": errs}))
    assert e.value.status == 422 and e.value.errors == errs


def test_a_reply_that_is_not_the_kits_shape_is_an_error():
    with pytest.raises(client.ClientError, match="500"):
        client.post_config({}, "http://k", transport=Recorder(500, None))
    with pytest.raises(client.ClientError, match="config_path"):
        client.post_config({}, "http://k", transport=Recorder(201, {"id": "a"}))


# ---- the command line

def run(argv, rec, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    code = client.main(argv, transport=rec, stdout=out, stderr=err, stdin=io.StringIO(stdin))
    return code, out.getvalue(), err.getvalue()


def test_cli_prints_the_run_command_on_success(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    reply = {"id": "corner-pc", "name": "Corner PC", "origin": "SIM", "config_path": "/x/corner-pc.json",
             "run_command": "cd /x/agents && .venv/bin/python sellers/seller_agent.py --config /x/corner-pc.json"}
    code, out, err = run([str(f)], Recorder(201, reply))
    assert code == 0 and err == ""
    assert reply["run_command"] in out and "SIM" in out and "/x/corner-pc.json" in out


def test_cli_reads_answers_from_stdin_with_a_dash():
    reply = {"id": "corner-pc", "config_path": "/x/c.json", "run_command": "RUNME"}
    code, out, _ = run(["-"], Recorder(201, reply), stdin=json.dumps(answers()))
    assert code == 0 and "RUNME" in out


def test_cli_down_exits_2_with_the_message_and_no_traceback(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    code, out, err = run([str(f)], Recorder(raises=OSError("down")))
    assert code == 2 and out == "" and "not running" in err and "Traceback" not in err


def test_cli_refusal_exits_1_and_lists_each_field(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    errs = [{"field": "name", "message": "bad"}, {"field": "origin", "message": "worse"}]
    code, out, err = run([str(f)], Recorder(422, {"errors": errs}))
    assert code == 1 and "name: bad" in err and "origin: worse" in err and "Nothing was saved" in err


def test_cli_taken_id_suggests_replace(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    code, _, err = run([str(f)], Recorder(409, {"errors": [{"field": "id", "message": "already a shop here"}]}))
    assert code == 1 and "--replace" in err


def test_cli_bad_input_file_is_a_message(tmp_path):
    code, _, err = run([str(tmp_path / "missing.json")], Recorder())
    assert code == 1 and "cannot read" in err
    f = tmp_path / "bad.json"
    f.write_text("{nope")
    code, _, err = run([str(f)], Recorder())
    assert code == 1 and "not valid JSON" in err


def test_dry_run_prints_the_config_and_makes_no_call(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    rec = Recorder()
    code, out, _ = run([str(f), "--dry-run"], rec)
    assert code == 0 and rec.calls == []
    assert json.loads(out)["id"] == "corner-pc"


def test_url_comes_from_the_flag_then_the_environment(tmp_path, monkeypatch):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    reply = {"id": "a", "config_path": "p", "run_command": "r"}
    monkeypatch.setenv("SELLER_KIT_URL", "http://127.0.0.1:9999")
    rec = Recorder(201, reply)
    run([str(f)], rec)
    assert rec.calls[0][1].startswith("http://127.0.0.1:9999/")
    rec = Recorder(201, reply)
    run([str(f), "--url", "http://127.0.0.1:8123"], rec)
    assert rec.calls[0][1].startswith("http://127.0.0.1:8123/")
    monkeypatch.delenv("SELLER_KIT_URL")
    rec = Recorder(201, reply)
    run([str(f)], rec)
    assert rec.calls[0][1].startswith("http://127.0.0.1:8791/")


def test_a_non_http_kit_url_is_refused_before_any_call(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps(answers()))
    rec = Recorder()
    code, _, err = run([str(f), "--url", "file:///etc/passwd"], rec)
    assert code == 1 and rec.calls == [] and "http" in err


def test_needs_lists_open_needs_with_their_origin():
    needs = [{"id": "n1", "sku_spec": GPU, "allowed_conditions": ["new"], "quantity": 1, "delivery_window": "by Friday", "origin": "SIM"}]
    rec = Recorder(200, needs)
    code, out, _ = run(["--needs"], rec)
    assert code == 0 and rec.calls[0][:2] == ("GET", "http://127.0.0.1:8791/v1/needs/open")
    assert GPU in out and "SIM" in out


# ---- against the real Seller Kit app (the guard the skill relies on)

def test_a_good_interview_is_accepted_by_the_real_kit_and_written(tmp_path):
    custom = tmp_path / "custom"
    out = client.post_config(client.build_config(answers()), "http://127.0.0.1:8791", transport=real_api_transport(custom))
    assert out["origin"] == "SIM" and Path(out["config_path"]) == custom / "corner-pc.json"
    assert (custom / "corner-pc.json").exists()


@pytest.mark.parametrize("item_over,field", [
    ({"floor": -5}, "floor_by_condition"),
    ({"floor": 1500}, "floor_by_condition"),
    ({"condition": "mint"}, "condition"),
    ({"url": "javascript:alert(1)"}, "listing_url"),
])
def test_the_real_kit_refuses_what_the_model_could_get_wrong(tmp_path, item_over, field):
    custom = tmp_path / "custom"
    item = dict(answers()["items"][0], **item_over)
    with pytest.raises(client.KitRefused) as e:
        client.post_config(client.build_config(answers(items=[item])), "http://127.0.0.1:8791", transport=real_api_transport(custom))
    assert any(field in x["field"] for x in e.value.errors), e.value.errors
    assert not custom.exists() or not list(custom.glob("*.json"))


# ---- packaging: the skill file and the plugin manifests

def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with frontmatter"
    fields = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fields[k.strip()] = v.strip()
    return fields


def test_skill_frontmatter_has_only_name_and_a_short_description():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    fm = frontmatter(text)
    assert set(fm) == {"name", "description"}
    assert fm["name"] == "tech-bazaar-seller"
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fm["name"]) and "claude" not in fm["name"] and "anthropic" not in fm["name"]
    assert 20 < len(fm["description"]) <= 1024
    assert "<" not in fm["description"]  # no XML-style tags in a skill description


def test_skill_text_has_no_em_or_en_dashes_and_names_the_client_and_the_fee_as_proposed():
    for p in [SKILL_DIR / "SKILL.md", SKILL_DIR / "seller_kit_client.py", REPO / "docs" / "SELLER_SKILL.md"]:
        text = p.read_text(encoding="utf-8")
        assert "—" not in text and "–" not in text, p
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "seller_kit_client.py" in skill
    assert "3 percent" in skill and "$25" in skill and "proposed" in skill.lower()


def test_skill_says_only_what_the_ranking_does_today_about_perks_and_returns():
    """market.ts calls rankBids without perksValue, so only condition and an N-day returns line (30 or more) move rank."""
    text = " ".join((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split())
    assert "condition and a returns policy of at least 30 days count" in text
    assert "other perks are shown to the buyer but do not change rank today" in text
    assert "perks all count" not in text and "not decoration" not in text


def test_skill_says_a_new_shops_agent_is_not_asked_to_bid_automatically():
    """buyer_agent.live_sellers() asks only common.SELLERS, so a custom seller bids once the buyer is told its address.
    Same wording as the /sell page (web/src/app/sell/page.tsx)."""
    text = " ".join((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").split())
    assert "The buyer agent only asks the sellers on its list." in text
    assert "Your agent bids once the buyer is told its address; that is not automatic yet." in text
    page = " ".join((REPO / "web" / "src" / "app" / "sell" / "page.tsx").read_text(encoding="utf-8").split())
    assert "The buyer agent only asks the sellers on its list. Your agent bids once the buyer is told its address; that is not automatic yet." in page


def test_marketplace_and_plugin_manifests_point_at_the_skill():
    mp = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    assert "claude" not in mp["name"] and "anthropic" not in mp["name"]
    entry = next(p for p in mp["plugins"] if p["name"] == "tech-bazaar-seller")
    assert entry["source"] == "./"
    # Claude Code refuses to load a plugin whose marketplace entry AND plugin.json both list components
    # ("conflicting manifests"), so the components live only in plugin.json.
    assert not {"skills", "agents", "commands", "hooks", "strict"} & set(entry)
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["name"] == "tech-bazaar-seller"
    # the skill lives under .claude/skills, not the default skills/ folder, so plugin.json names it
    assert [(REPO / s).resolve() for s in plugin["skills"]] == [SKILL_DIR.resolve()]
    # the repo's agents/ folder holds Fetch agent code and notes, not Claude subagents: an empty list stops the
    # plugin loader from registering its markdown files as agents
    assert plugin["agents"] == []
    assert (SKILL_DIR / "SKILL.md").is_file()
