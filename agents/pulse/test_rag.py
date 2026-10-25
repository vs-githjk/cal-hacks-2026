"""Market Pulse phase 2: retrieval with citations over our own rounds, listings and CRS rows.
Every provider is an in-memory fake: no network, no key, no real file (except where a test says so)."""
import asyncio
import copy
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.pulse import fair_band as FB  # noqa: E402
from agents.pulse import orchestrator as O  # noqa: E402
from agents.pulse import rag as R  # noqa: E402
from agents.pulse.test_orchestrator import CATALOG, NOW, FakeCtx, FakeSource, _own_event_loop, fresh_loop  # noqa: E402,F401

SKU = "rtx 5070 ti"
CITE = re.compile(r"\[\d+(?:, \d+)*\]")
MONEY = re.compile(r"\$[\d,]+(?:\.\d\d)?")


def ask_now():
    return NOW   # 2026-10-24 18:00 UTC


def listing(price, day, store="bestbuy", sku=SKU, url=None, kind="ask", in_stock=True, condition="new"):
    return {"sku": sku, "price": price, "in_stock": in_stock, "kind": kind, "store": store, "condition": condition,
            "observed_at": f"2026-10-{day:02d}T05:00:00Z", "origin": "MIRROR", "snapshot_id": f"{store}-202610{day:02d}T0500Z",
            "url": url or f"https://www.{store}.com/p/{sku.replace(' ', '-')}-{price}", "title": f"{store} {sku} card"}


SNAPS = [listing(1200.0, 23), listing(1210.0, 23, "microcenter"), listing(1220.0, 23, "bh"),
         listing(1250.0, 24), listing(1260.0, 24, "microcenter"), listing(1270.0, 24, "bh"),
         listing(640.0, 24, "ebay_sold", kind="sold"), listing(900.0, 24, "centralcomputers"),
         listing(1000.0, 10)]                                              # a month old: outside "this week"


def rnd(round_id, winner, sku=SKU, others=("b", "c"), origin="SIM", day=24, persona=None):
    rows = [{"round_id": round_id, "seller_id": winner, "rank": 1, "origin": origin, "reasons": [],
             "lines": [{"sku_spec": sku, "unit_price": 111.11}], "landed": 111.11, "persona": persona or f"{winner} (SIM)"}]
    for i, s in enumerate(others, 2):
        rows.append({"round_id": round_id, "seller_id": s, "rank": i, "origin": origin, "reasons": [],
                     "lines": [{"sku_spec": sku, "unit_price": 222.22 + i}], "landed": 222.22 + i})
    rows.append({"round_id": round_id, "seller_id": "dq", "rank": 0, "origin": origin, "reasons": ["fit: too long"],
                 "lines": [{"sku_spec": sku, "unit_price": 333.33}], "landed": 333.33})
    return {"round_id": round_id, "rows": rows, "date": f"2026-10-{day:02d}"}


ROUNDS = [rnd("round-1", "shady-sam"), rnd("round-2", "seller_1", day=24), rnd("round-3", "seller_1", day=23),
          rnd("round-4", "seller_5", sku="psu 750w")]
CRS = {"seller_1": {"supplier_id": "seller_1", "stability": "verified_stable", "checked_at": "2026-10-24T08:00:00Z", "source": "sandbox"},
       "seller_3": {"supplier_id": "seller_3", "stability": "not_verified", "checked_at": "2026-10-20T08:00:00Z", "source": "recorded"},
       "seller_5": {"supplier_id": "seller_5", "stability": "caution", "checked_at": "2026-10-24T09:00:00Z", "source": "simulated"}}


def rag(**kw):
    args = dict(rounds=lambda: copy.deepcopy(ROUNDS), snapshots=lambda: copy.deepcopy(SNAPS), crs=lambda: copy.deepcopy(CRS),
                tiger_rows=lambda sku, days: {"status": "not_configured", "rows": []}, catalog=copy.deepcopy(CATALOG), now=ask_now)
    args.update(kw)
    return R.Rag(**args)


def ask(q, r=None, **kw):
    r = r or rag(**kw)
    sku = O.match_sku(__import__("re").findall(r"[a-z0-9]+", q.lower()), ["rtx 5070 ti", "psu 750w", "rtx 4070 super 12gb"])
    seller = r.match_seller(q.lower())
    return r.answer(q, sku=sku, seller=seller)


def lines_with_claims(out):
    return [l for l in out["lines"] if l["cites"]]


# ---- BM25 -----------------------------------------------------------------------

def doc(i, text, kind="listing"):
    return R.Doc(id=i, kind=kind, text=text, origin="MIRROR", source="s", date="2026-10-24", url="", ref=i, fields={})


def test_bm25_ranks_the_row_with_more_of_the_query_first_and_ties_break_by_id():
    docs = [doc("a", "rtx 5070 ti bestbuy"), doc("b", "rtx 5070 ti 16gb bestbuy listing"), doc("c", "psu 750w corsair"), doc("d", "rtx 5070 ti bestbuy")]
    hits = R.BM25(docs).search("rtx 5070 ti bestbuy listing")
    assert [d.id for _, d in hits] == ["b", "a", "d"]                       # c shares no term; a and d tie, id order
    assert [d.id for _, d in R.BM25(docs).search("rtx 5070 ti bestbuy listing")] == ["b", "a", "d"]


def test_bm25_is_deterministic_filters_by_kind_and_returns_nothing_for_unknown_words():
    docs = [doc("a", "rtx listing"), doc("b", "rtx round", kind="round")]
    idx = R.BM25(docs)
    assert [d.id for _, d in idx.search("rtx", kinds={"round"})] == ["b"]
    assert idx.search("zzzz qqqq") == [] and idx.search("") == [] and R.BM25([]).search("rtx") == []
    assert idx.search("the and of") == []                                    # stop words alone match nothing


def test_bm25_limit_caps_the_hits():
    docs = [doc(f"d{i:02d}", "rtx listing") for i in range(30)]
    assert len(R.BM25(docs).search("rtx", limit=5)) == 5


# ---- price moves ----------------------------------------------------------------

def test_how_did_prices_move_this_week_gives_a_cited_median_per_day_and_the_change():
    out = ask("how did RTX 5070 Ti prices move this week?")
    text = out["text"]
    assert out["intent"] == "price_move"
    assert "2026-10-23: 3 retail asks, median $1,210.00" in text and "2026-10-24: 3 retail asks, median $1,260.00" in text
    assert "rose" in text and "4.1%" in text                                 # 1210 -> 1260
    assert all(l["cites"] for l in out["lines"]) and "(MIRROR)" in text
    assert "ebay_sold" not in text and "$640" not in text and "$900" not in text   # sold prices and the local store stay out
    assert "$1,000.00" not in text                                          # 14 days old: outside the week


def test_the_sources_list_names_source_date_and_url_for_each_citation():
    out = ask("how did RTX 5070 Ti prices move this week?")
    assert out["evidence"] and all({"id", "source", "date", "url", "origin", "n"} <= set(e) for e in out["evidence"])
    srcs = out["text"].split("Sources:")[1]
    assert re.search(r"\[1\] .*2026-10-23.*https://", srcs) and "(MIRROR)" in srcs


def test_one_day_of_listings_is_not_called_a_move():
    out = ask("how did RTX 5070 Ti prices move this week?", snapshots=lambda: [s for s in SNAPS if s["observed_at"].startswith("2026-10-24")])
    assert "only 1 day" in out["text"] and "rose" not in out["text"] and "fell" not in out["text"]
    assert all(l["cites"] for l in out["lines"])


def test_a_fall_is_called_a_fall_and_a_flat_week_is_flat():
    down = [listing(p, d, s) for d, ps in ((23, (1300.0, 1310.0, 1320.0)), (24, (1200.0, 1210.0, 1220.0))) for p, s in zip(ps, ("bestbuy", "microcenter", "bh"))]
    assert "fell" in ask("how did RTX 5070 Ti prices move this week?", snapshots=lambda: down)["text"]
    flat = [listing(p, d, s) for d in (23, 24) for p, s in zip((1200.0, 1210.0, 1220.0), ("bestbuy", "microcenter", "bh"))]
    assert "held flat" in ask("how did RTX 5070 Ti prices move this week?", snapshots=lambda: flat)["text"]


def test_no_listings_means_no_data_and_no_claim():
    out = ask("how did RTX 5070 Ti prices move this week?", snapshots=lambda: [])
    assert "no dated prices" in out["text"] and not lines_with_claims(out) and not MONEY.search(out["text"])


def test_tiger_rows_are_used_when_present_and_sim_rows_never_are():
    def tiger(sku, days):
        return {"status": "ok", "rows": [
            {"price_cents": 130000, "ts": NOW - timedelta(days=2), "origin": "MIRROR", "url": "https://shop.example/a"},
            {"price_cents": 131000, "ts": NOW - timedelta(days=2), "origin": "MIRROR", "url": ""},
            {"price_cents": 125000, "ts": NOW - timedelta(days=1), "origin": "MIRROR", "url": "https://shop.example/b"},
            {"price_cents": 99900, "ts": NOW - timedelta(days=1), "origin": "SIM", "url": ""}]}
    out = ask("how did RTX 5070 Ti prices move this week?", tiger_rows=tiger)
    assert "Tiger Data price_obs" in out["text"] and "$1,305.00" in out["text"] and "$1,250.00" in out["text"] and "fell" in out["text"]
    assert "$999" not in out["text"]


def test_a_month_question_widens_the_window():
    out = ask("how did RTX 5070 Ti prices change this month?")
    assert "2026-10-10" in out["text"]


# ---- who won -----------------------------------------------------------------------

def test_which_seller_won_most_gpu_rounds_counts_winners_and_cites_each_round():
    out = ask("which seller won most GPU rounds?")
    assert out["intent"] == "winners"
    assert "seller_1" in out["text"] and "2 of 3" in out["text"]            # the psu round is not a GPU round
    assert "round-2" in out["text"] and "round-3" in out["text"] and "round-4" not in out["text"]
    assert all(l["cites"] for l in out["lines"]) and "(SIM)" in out["text"]


def test_a_tie_is_reported_as_a_tie_not_decided():
    two = [rnd("r1", "x"), rnd("r2", "y")]
    text = ask("who won the most rounds", rounds=lambda: two)["text"]
    assert "tied" in text.lower() and "x" in text and "y" in text


def test_winner_answers_carry_no_prices_at_all_whatever_the_rounds_hold():
    out = ask("which seller won most GPU rounds?")
    for n in ("111.11", "222", "333.33", "$"):
        assert n not in out["text"]


def test_no_rounds_means_no_data():
    out = ask("which seller won most GPU rounds?", rounds=lambda: [])
    assert "no finished rounds" in out["text"] and not lines_with_claims(out)


def test_a_round_with_two_winners_or_none_is_left_out_not_guessed():
    bad = [rnd("r1", "x"), {"round_id": "r2", "rows": [dict(rnd("r2", "y")["rows"][0], rank=2)], "date": "2026-10-24"}]
    assert "1 of 1" in ask("which seller won most rounds?", rounds=lambda: bad)["text"]


# ---- CRS ----------------------------------------------------------------------------

def test_is_byte_bros_crs_verified_cites_the_check_and_says_how_old_it_is():
    out = ask("is Byte Bros CRS verified?", catalog={**copy.deepcopy(CATALOG), "seller_1": {"name": "Byte Bros Outlet", "skus": []}})
    assert out["intent"] == "crs"
    assert "Byte Bros Outlet" in out["text"] and "verified stable" in out["text"] and "2026-10-24T08:00:00Z" in out["text"]
    assert "CRS sandbox" in out["text"] and "(LIVE)" in out["text"] and "[1]" in out["text"]


def test_an_old_check_is_said_to_be_old_and_a_simulated_one_is_sim():
    stale = ask("is FlashDeal Frankie CRS verified?")["text"]
    assert "not verified" in stale and "older than 24 hours" in stale
    sim = ask("is ReNew Refurb CRS verified?")["text"]
    assert "caution" in sim and "(SIM)" in sim


def test_a_seller_with_no_check_is_not_called_verified():
    text = ask("is Tenth Seller CRS verified?")["text"]
    assert "no CRS check on record" in text and "verified stable" not in text


def test_which_sellers_are_crs_verified_lists_every_check_with_its_own_citation():
    out = ask("which sellers are CRS verified?")
    assert out["text"].count("seller_1") >= 1 and out["text"].count("seller_3") >= 1 and len(out["evidence"]) == 3


def test_the_crs_cache_file_formats_both_read(tmp_path):
    entry = {"seller_1": {"persona_ref": "P01", "signal": CRS["seller_1"], "reason": "x"}}
    p = tmp_path / "crs.json"
    p.write_text(json.dumps(entry))
    assert R.read_crs_rows(p)["seller_1"]["stability"] == "verified_stable"
    q = tmp_path / "fixture.json"
    q.write_text(json.dumps([{"supplier_id": "seller_2", "stability": "verified_stable", "checked_at": "2026-10-24T08:00:00Z", "source": "simulated"}]))
    assert R.read_crs_rows(q)["seller_2"]["source"] == "simulated"
    assert R.read_crs_rows(tmp_path / "missing.json") == {}
    (tmp_path / "bad.json").write_text("not json")
    assert R.read_crs_rows(tmp_path / "bad.json") == {}


# ---- the rules -------------------------------------------------------------------------

QUESTIONS = ["how did RTX 5070 Ti prices move this week?", "which seller won most GPU rounds?", "is Byte Bros CRS verified?",
             "which sellers are CRS verified?", "show me RTX 5070 Ti listings"]


@pytest.mark.parametrize("q", QUESTIONS)
def test_no_citation_means_no_claim(q):
    out = ask(q)
    assert out is not None
    for l in out["lines"]:
        assert l["cites"] or l.get("none") is True, l                      # a line is either cited or an explicit "no data" statement
    cited = {int(n) for m in CITE.findall(out["text"]) for n in re.findall(r"\d+", m)}
    assert cited <= {e["id"] for e in out["evidence"]} and cited


@pytest.mark.parametrize("q", QUESTIONS)
def test_every_answer_says_what_its_sources_are_labelled_and_never_ranks_or_decides(q):
    text = ask(q)["text"]
    assert re.search(r"\((LIVE|MIRROR|SIM)\)", text) and "Sources:" in text
    for banned in ("you should", "i recommend", "best choice", "buy it", "i approve", "cheapest seller"):
        assert banned not in text.lower()


def test_a_sellers_catalog_price_is_never_in_the_index():
    """The SIM catalog (agents/sellers/sellers.json) has no reader in the module: only rounds, MIRROR listings and CRS rows are indexed."""
    assert not hasattr(R, "SELLERS_JSON") and not hasattr(R, "default_catalog")
    assert "json.loads" in Path(R.__file__).read_text()                           # it does read files ...
    assert "sellers.json" not in "\n".join(l for l in Path(R.__file__).read_text().splitlines() if "open(" in l or "read_text" in l)
    assert {d.kind for d in rag().index().docs} == {"listing", "round", "crs"}
    sim_prices = json.loads((ROOT / "agents" / "sellers" / "sellers.json").read_text())["sellers"]
    only_sim = {l.get("price") for s in sim_prices.values() if s.get("origin") == "SIM" for l in (s.get("listings") or {}).values()}
    default_docs = R.Rag.default(catalog={}).index().docs
    assert not [d for d in default_docs if d.kind == "listing" and d.fields["store"].startswith("seller")]
    assert only_sim and not [d for d in default_docs if d.kind == "round" and re.search(r"\d+\.\d\d", d.text)]


def test_round_rows_in_the_index_hold_no_price(tmp_path):
    for d in rag().index().docs:
        if d.kind == "round":
            assert not re.search(r"\d+\.\d\d", d.text)


def test_a_question_that_is_not_about_our_data_is_left_to_the_other_answers():
    assert ask("what is the weather today?") is None
    assert ask("why does seller_3 keep losing?") is None
    assert ask("how is the RTX 5070 Ti trending?") is None


def test_the_same_page_read_twice_counts_once_in_listings_and_in_the_daily_median():
    twice = SNAPS + [dict(s) for s in SNAPS if s["observed_at"].startswith("2026-10-24") and s["kind"] == "ask"]
    assert "2026-10-24: 3 retail asks" in ask("how did RTX 5070 Ti prices move this week?", snapshots=lambda: twice)["text"]
    shown = ask("show me RTX 5070 Ti listings", snapshots=lambda: twice)["text"].split("Sources:")[0]
    assert len(set(shown.splitlines())) == len(shown.splitlines())


def test_listing_questions_show_newest_public_asks_with_url_and_date():
    out = ask("show me RTX 5070 Ti listings")
    assert out["intent"] == "listings" and "https://" in out["text"] and "2026-10-24" in out["text"] and "ebay_sold" not in out["text"]
    assert out["text"].count("\n") < 14


# ---- optional phrasing by Claude, every claim kept ----------------------------------------

def test_without_a_writer_the_answer_is_the_deterministic_one():
    assert ask("how did RTX 5070 Ti prices move this week?")["phrased_by"] == "template"


def good_writer(facts):
    return {"lines": [l["text"].replace("retail asks", "retail prices") for l in facts["lines"]]}


def test_a_valid_rewrite_is_used_and_still_cited():
    out = ask("how did RTX 5070 Ti prices move this week?", writer=good_writer)
    assert out["phrased_by"] == "Claude" and "retail prices" in out["text"] and all(l["cites"] for l in out["lines"])


@pytest.mark.parametrize("bad", [
    lambda f: {"lines": [t["text"] + " It will rise 9% next week." for t in f["lines"]]},     # a new number
    lambda f: {"lines": [re.sub(r" \[\d+(, \d+)*\]", "", t["text"]) for t in f["lines"]]},     # citations dropped
    lambda f: {"lines": ["only one line"]},                                                    # wrong number of lines
    lambda f: {"lines": [t["text"] + "x" * 900 for t in f["lines"]]},                          # far too long
    lambda f: {"lines": [5 for _ in f["lines"]]},                                              # not text
    lambda f: "nonsense", lambda f: None,
])
def test_an_unusable_rewrite_falls_back_per_line_to_the_template(bad):
    base = ask("how did RTX 5070 Ti prices move this week?")
    out = ask("how did RTX 5070 Ti prices move this week?", writer=bad)
    assert out["lines"] == base["lines"] and out["phrased_by"] == "template"


def test_a_writer_that_raises_never_breaks_the_answer():
    def boom(facts):
        raise RuntimeError("api down")
    assert ask("how did RTX 5070 Ti prices move this week?", writer=boom)["phrased_by"] == "template"


def test_the_writer_sees_only_retrieved_lines_and_the_question_marked_as_data():
    seen = {}

    def spy(facts):
        seen.update(facts)
        return None
    ask("how did RTX 5070 Ti prices move this week?", writer=spy)
    assert set(seen) == {"question", "lines"} and all(set(l) == {"text", "cites"} for l in seen["lines"])


def test_the_live_writer_is_off_without_the_flag_and_the_key(monkeypatch):
    monkeypatch.delenv("PULSE_CLAUDE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert R.claude_writer() is None
    monkeypatch.setenv("PULSE_CLAUDE", "1")
    assert R.claude_writer() is None
    assert R.MODEL == "claude-haiku-5-5"


# ---- the round store -----------------------------------------------------------------------

def test_a_finished_round_is_saved_without_prices_and_loaded_back(tmp_path):
    rows = rnd("round-9", "seller_1")["rows"]
    path = R.save_round({"round_result": [dict(r, adjusted_total=r["landed"], bid_id="b") for r in rows], "loss_reports": []}, tmp_path,
                        now=ask_now)
    saved = json.loads(path.read_text())
    assert path.name == "round-9.json" and saved["saved_at"] == "2026-10-24T18:00:00Z"
    assert "111.11" not in path.read_text() and "unit_price" not in path.read_text() and "landed" not in path.read_text()
    loaded = R.load_rounds([tmp_path])
    assert loaded[0]["round_id"] == "round-9" and loaded[0]["date"] == "2026-10-24"
    winner = [r for r in loaded[0]["rows"] if r["rank"] == 1][0]
    assert winner["seller_id"] == "seller_1" and winner["sku"] == SKU


@pytest.mark.parametrize("bad", [{}, {"round_result": []}, {"round_result": [{"round_id": "../x", "seller_id": "a", "rank": 1, "lines": [{"sku_spec": "x"}]}]},
                                 {"round_result": [{"round_id": "r", "seller_id": "a", "rank": "1", "lines": []}]}, "text", None])
def test_a_round_that_cannot_be_read_is_not_saved(tmp_path, bad):
    assert R.save_round(bad, tmp_path, now=ask_now) is None and list(tmp_path.iterdir()) == []


def test_the_repo_sample_round_loads_as_a_sim_round_won_by_shady_sam():
    rounds = R.load_rounds([ROOT / "agents" / "pulse" / "fixtures"])
    assert rounds[0]["round_id"] == "round-1"
    assert [r["seller_id"] for r in rounds[0]["rows"] if r["rank"] == 1] == ["shady-sam"]


def test_unreadable_round_files_are_skipped(tmp_path):
    (tmp_path / "a.json").write_text("not json")
    (tmp_path / "b.json").write_text(json.dumps({"round_id": "x"}))
    assert R.load_rounds([tmp_path]) == []


# ---- chat ------------------------------------------------------------------------------------

def pulse_with_rag(tmp_path, **kw):
    p = O.Pulse(FakeSource(), catalog=copy.deepcopy(CATALOG), crs_path=tmp_path / "none.json", now=lambda: NOW,
                bands=__import__("agents.pulse.test_orchestrator", fromlist=["fixed_bands"]).fixed_bands(), rag=rag(**kw))
    return p


def test_pulse_chat_answers_the_three_questions_from_retrieved_rows(tmp_path):
    p = pulse_with_rag(tmp_path)
    move = p.answer("how did RTX 5070 Ti prices move this week?")
    assert "median" in move and "Sources:" in move and "[1]" in move
    won = p.answer("which seller won most GPU rounds?")
    assert "seller_1" in won and "round-2" in won
    crs = p.answer("is Byte Bros CRS verified?")
    assert "CRS sandbox" in crs and "Sources:" in crs


def test_the_older_chat_answers_are_unchanged(tmp_path):
    p = pulse_with_rag(tmp_path)
    assert p.answer("how is the RTX 5070 Ti trending?").startswith("RTX 5070 TI: the week and the month.")
    assert p.answer("what's the going price for an RTX 5070 Ti?").startswith("RTX 5070 TI: typical $1,279.00")
    assert p.answer("what is the cap?") == O.HELP


def test_a_sellers_record_is_still_only_for_its_own_agent_and_rag_never_answers_it(tmp_path):
    p = pulse_with_rag(tmp_path)
    assert p.answer("why does seller_3 keep losing?", lambda sid: False) == "I only answer a seller's record to that seller's own agent."


def test_the_help_names_the_new_questions():
    assert "this week" in O.HELP and "CRS" in O.HELP and "won" in O.HELP


def test_a_failing_rag_never_breaks_chat(tmp_path):
    class Broken:
        catalog = {}

        def answer(self, *a, **k):
            raise RuntimeError("boom")
    p = pulse_with_rag(tmp_path)
    p.rag = Broken()
    assert p.answer("how did RTX 5070 Ti prices move this week?").startswith("RTX 5070 TI: the week and the month.")


def test_the_agent_saves_each_referee_round_for_later_questions(tmp_path, monkeypatch):
    pytest.importorskip("uagents")
    monkeypatch.setenv("PULSE_ROUND_DIR", str(tmp_path / "rounds"))
    monkeypatch.setenv("PULSE_PUBLIC_PATH", str(tmp_path / "pub" / "latest.json"))
    monkeypatch.setenv("PULSE_ROUND_SENDERS", "agent1qreferee")
    monkeypatch.delenv("PULSE_MAILBOX", raising=False)
    monkeypatch.delenv("AGENTS_MAILBOX", raising=False)
    fresh_loop()
    agent = O.build_agent(pulse_with_rag(tmp_path), port=8928)
    import common
    monkeypatch.setattr(common, "screen", lambda *a, **k: {"verdict": "allow"})
    handler = next(fn for fn in agent._protocol._signed_message_handlers.values() if fn.__name__ == "on_round")
    ctx = FakeCtx()
    ctx.session = "s"
    ctx.logger = type("L", (), {"warning": lambda *a, **k: None, "info": lambda *a, **k: None})()
    data = json.loads((ROOT / "agents" / "pulse" / "fixtures" / "round1_sample.json").read_text())
    asyncio.run(handler(ctx, "agent1qreferee", agent.pulse_models[0](round_json=json.dumps(data))))
    assert (tmp_path / "rounds" / "round-1.json").exists()


# ---- command line --------------------------------------------------------------------------------

def test_cli_prints_the_answer(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("PULSE_ROUND_DIR", str(tmp_path / "none"))
    monkeypatch.delenv(O.store.ENV, raising=False)
    assert R.main(["which seller won most GPU rounds?"]) == 0
    out = capsys.readouterr().out
    assert "Sources:" in out and "shady-sam" in out
