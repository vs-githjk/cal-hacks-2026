"""#189 memory store: entries for the #123 dashboard panel, built only from demo run files and market rows.
Fake SQL and temp dirs only; no SpacetimeDB, no network."""
import json
import shutil
from pathlib import Path

import pytest

from demo import memory as M
from demo.common import schema_errors

SAMPLE = Path(__file__).resolve().parents[1] / "out" / "sample-run.json"


def _sample():
    return json.loads(SAMPLE.read_text())


def _valid(entries):
    for e in entries:
        assert schema_errors("MemoryEntry", e) == [], (e["id"], schema_errors("MemoryEntry", e))


# ---------------------------------------------------------------- demo runs

def test_a_demo_run_gives_its_goal_purchase_vetoes_and_lessons():
    run = _sample()
    got = M.from_demo_run(run, "run-x")
    _valid(got)
    kinds = [e["kind"] for e in got]
    assert kinds.count("goal") == 1 and kinds.count("purchase") == 1
    assert "veto" in kinds and "lesson" in kinds
    goal = next(e for e in got if e["kind"] == "goal")
    assert goal["detail"]["cap"] == 1300.0 and goal["detail"]["items"][0]["sku_spec"] == "rtx 5070 ti"
    assert goal["origin"] == "SIM" and goal["source"] == "demo_run" and goal["source_ref"] == "run-x"


def test_a_demo_purchase_is_sim_with_the_price_before_tax_and_the_payment_mode():
    run = _sample()
    p = next(e for e in M.from_demo_run(run, "run-x") if e["kind"] == "purchase")
    d = p["detail"]
    assert p["origin"] == "SIM"                       # no real money moves this weekend
    assert d["amount_before_tax"] == run["artifacts"]["mandate"]["amount"]
    assert d["payment_mode"] == "sim" and d["listing_origin"] == "MIRROR"
    assert d["approval_method"] == "sim_script"       # the scripted run's approval, not a phone call
    assert p["seller_id"] == "best-buy" and "1,299.99" in p["summary"] and "Best Buy" in p["summary"]


def test_vetoes_carry_the_rule_id_and_source_url():
    vetoes = [e for e in M.from_demo_run(_sample(), "run-x") if e["kind"] == "veto"]
    assert vetoes
    for v in vetoes:
        assert "." in v["detail"]["rule_id"] and v["detail"]["reason"]
        assert v["seller_id"]


def test_lessons_are_bands_never_raw_numbers():
    lessons = [e for e in M.from_demo_run(_sample(), "run-x") if e["kind"] == "lesson"]
    assert lessons
    for e in lessons:
        assert e["detail"]["gap_band"] in ("within5", "within10", "within20", "over20")
        assert set(e["detail"]) == {"round_id", "won", "reason", "gap_band", "what_to_change"}
        assert e["origin"] == "SIM"                   # demo/learning.py is a stand-in


def test_a_run_with_no_approval_or_charge_has_no_purchase():
    run = _sample()
    run["artifacts"]["approval_record"]["result"] = "denied"
    run["artifacts"]["charge"] = None
    assert not [e for e in M.from_demo_run(run, "run-x") if e["kind"] == "purchase"]


def test_a_broken_run_file_gives_no_rows_and_no_error():
    assert M.from_demo_run({"artifacts": "nope"}, "run-x") == []
    assert M.from_demo_run({}, "run-x") == []


# ---------------------------------------------------------------- market rows

def fake_sql(tables):
    def sql(query):
        for name, rows in tables.items():
            if query.endswith(f" FROM {name}"):
                return rows
        return []
    return sql


MARKET = {
    "goal": [['"goal-1"', '"vidyut"', "1300", "2026-10-30T23:59:00+00:00", '"SIM"', "2026-10-24T18:00:00+00:00"]],
    "goal_item": [['"goal-1"', '"rtx 5070 ti"', '"new"', "1"]],
    "mandate": [['"h1"', '"mnd_1"', '"deal-bid-1"', '"vidyut"', "1299.99", '"best-buy@pay.example.test"', '"MIRROR"'],
                ['"h2"', '"mnd_2"', '"deal-bid-2"', '"vidyut"', "999", '"x@pay.example.test"', '"MIRROR"']],
    "approval": [['"h1"', '"voice_code"', "2026-10-24T18:02:00+00:00"]],
    "payment": [['"h1"', '"ch_test_1"', "1299.99", "2026-10-24T18:02:05+00:00", '"stripe_test"']],
    "bid": [['"bid-1"', '"best-buy"', '"Best Buy"'], ['"bid-9"', '"shady-sam"', '"Shady Sam (SIM)"']],
    "bid_check": [['"bid-9"', '"advocate"', '"veto"', '"advocate.condition The page shows used"', '"http://127.0.0.1:8765/p.html"',
                   '"SIM"', "2026-10-24T18:01:00+00:00"],
                  ['"bid-1"', '"advocate"', '"buy"', '"advocate.ok fine"', '""', '"MIRROR"', "2026-10-24T18:01:00+00:00"]],
    "loss_report": [['"lr-1"', '"round-1"', '"amazon-direct"', "false", '"within5"', '"price"', '"Lower by 3%"', '"MIRROR"',
                     "2026-10-24T18:03:00+00:00"]],
}


def test_market_rows_become_entries_with_the_market_label():
    got = M.from_market(fake_sql(MARKET), "market:tech-bazaar@t")
    _valid(got)
    by = {e["kind"]: [x for x in got if x["kind"] == e["kind"]] for e in got}
    assert len(by["goal"]) == 1 and by["goal"][0]["detail"]["items"][0]["sku_spec"] == "rtx 5070 ti"
    assert len(by["purchase"]) == 1                    # h2 has no payment row: not a purchase
    p = by["purchase"][0]
    assert p["origin"] == "SIM" and p["detail"]["payment_mode"] == "stripe_test"   # test mode: still no real money
    assert p["detail"]["approval_method"] == "voice_code" and p["seller_id"] == "best-buy"
    assert p["detail"]["listing_origin"] == "MIRROR" and p["at"] == "2026-10-24T18:02:05+00:00"
    assert [v["seller_id"] for v in by["veto"]] == ["shady-sam"]
    assert by["veto"][0]["detail"]["rule_id"] == "advocate.condition"
    assert by["lesson"][0]["origin"] == "MIRROR" and by["lesson"][0]["detail"]["gap_band"] == "within5"
    assert all(e["source"] == "market" for e in got)


def test_a_market_row_with_an_unknown_origin_is_labelled_sim():
    t = dict(MARKET, loss_report=[MARKET["loss_report"][0][:7] + ['"REAL"', "2026-10-24T18:03:00+00:00"]])
    lesson = next(e for e in M.from_market(fake_sql(t), "m") if e["kind"] == "lesson")
    assert lesson["origin"] == "SIM"


def test_a_lesson_with_an_unknown_band_is_dropped_not_guessed():
    t = dict(MARKET, loss_report=[MARKET["loss_report"][0][:4] + ['"12.5"'] + MARKET["loss_report"][0][5:]])
    assert not [e for e in M.from_market(fake_sql(t), "m") if e["kind"] == "lesson"]


def test_a_failing_market_read_raises_for_the_caller_to_report():
    def boom(q):
        raise RuntimeError("spacetime sql exited 1")
    with pytest.raises(RuntimeError):
        M.from_market(boom, "m")


# ---------------------------------------------------------------- snapshot and load

def test_snapshot_writes_market_rows_and_load_reads_the_newest(tmp_path):
    path = M.snapshot(fake_sql(MARKET), tmp_path, db="tech-bazaar", now="20261024T1805Z")
    assert path.name == "market-memory-20261024T1805Z.json"
    old = tmp_path / "market-memory-20261024T1000Z.json"
    old.write_text(json.dumps({"taken_at": "x", "db": "tech-bazaar", "entries": [], "error": None}))
    out = M.load(tmp_path)
    assert {e["source"] for e in out["entries"]} == {"market"}
    assert out["sources"][0]["ref"].endswith("20261024T1805Z.json") and out["sources"][0]["state"] == "ok"


def test_a_failed_snapshot_is_recorded_with_no_rows(tmp_path):
    def boom(q):
        raise RuntimeError("spacetime sql exited 1: no such database")
    path = M.snapshot(boom, tmp_path, db="tech-bazaar", now="20261024T1805Z")
    saved = json.loads(path.read_text())
    assert saved["entries"] == [] and "no such database" in saved["error"]
    out = M.load(tmp_path)
    assert out["entries"] == [] and out["sources"][0]["state"] == "error"


def test_load_reads_run_files_newest_first_and_skips_the_sample_unless_asked(tmp_path):
    shutil.copy(SAMPLE, tmp_path / "sample-run.json")
    run = _sample()
    run["run_id"] = "run-20261024T120000Z"
    run["generated_at"] = "2026-10-24T12:00:00Z"
    (tmp_path / "run-20261024T120000Z.json").write_text(json.dumps(run))
    out = M.load(tmp_path)
    assert {e["source_ref"] for e in out["entries"]} == {"run-20261024T120000Z"}
    ats = [e["at"] for e in out["entries"] if e["at"]]
    assert ats == sorted(ats, reverse=True)
    with_sample = M.load(tmp_path, include_sample=True)
    assert any(s["ref"] == "sample-run.json" and s["sample"] for s in with_sample["sources"])
    assert len(with_sample["entries"]) > len(out["entries"])


def test_nothing_recorded_gives_an_empty_answer_that_says_so(tmp_path):
    out = M.load(tmp_path / "missing")
    assert out == {"entries": [], "sources": [], "note": "no demo runs or market snapshots recorded yet"}


def test_an_unreadable_run_file_is_listed_as_an_error_not_skipped_silently(tmp_path):
    (tmp_path / "run-bad.json").write_text("{not json")
    out = M.load(tmp_path)
    assert out["entries"] == [] and out["sources"] == [{"ref": "run-bad.json", "kind": "demo_run", "state": "error",
                                                        "sample": False, "rows": 0}]


def test_kind_filter_and_limit(tmp_path):
    shutil.copy(SAMPLE, tmp_path / "run-a.json")
    out = M.load(tmp_path, kind="veto", limit=1)
    assert len(out["entries"]) == 1 and out["entries"][0]["kind"] == "veto"



# ---------------------------------------------------------------- #255 review 1

def test_bad_rows_in_a_snapshot_never_break_load(tmp_path):
    good = M.from_market(fake_sql(MARKET), "m")
    bad = [{"kind": "goal"}, {**good[0], "at": None}, {**good[0], "id": 5}, {**good[0], "origin": "REAL"}, "x", None]
    (tmp_path / "market-memory-20261024T1805Z.json").write_text(json.dumps({"entries": good + bad, "error": None}))
    out = M.load(tmp_path)
    assert len(out["entries"]) == len(good) and out["sources"][0]["dropped"] == len(bad)


def test_a_run_file_with_a_number_for_a_time_still_loads(tmp_path):
    run = _sample()
    run["artifacts"]["goal"]["created_at"] = 12345
    (tmp_path / "run-a.json").write_text(json.dumps(run))
    assert all(isinstance(e["at"], str) for e in M.load(tmp_path)["entries"])


def test_a_payment_that_disagrees_with_its_mandate_or_has_no_approval_is_not_a_purchase():
    t = dict(MARKET, payment=[['"h1"', '"ch_test_1"', "999.0", "2026-10-24T18:02:05+00:00", '"sim"']])
    stats = {}
    assert not [e for e in M.from_market(fake_sql(t), "m", stats) if e["kind"] == "purchase"] and stats["dropped"] >= 1
    t = dict(MARKET, approval=[])
    assert not [e for e in M.from_market(fake_sql(t), "m") if e["kind"] == "purchase"]


def test_a_split_cell_is_counted_as_dropped_not_guessed():
    t = dict(MARKET, bid=MARKET["bid"] + [['"bid-3"', '"x"', '"Bad', 'Persona"']])
    stats = {}
    M.from_market(fake_sql(t), "m", stats)
    assert stats["dropped"] == 1


def test_only_an_exact_mode_reads_as_stripe_test():
    run = _sample()
    run["artifacts"]["charge"]["mode"] = "Stripe LIVE latest"
    p = next(e for e in M.from_demo_run(run, "r") if e["kind"] == "purchase")
    assert p["detail"]["payment_mode"] == "none" and p["origin"] == "SIM"



# ---------------------------------------------------------------- #255 review 2

@pytest.mark.parametrize("text", ['{"entries": [], "dropped": Infinity}', "[" * 100000])
def test_hostile_snapshots_are_an_error_source_not_a_crash(tmp_path, text):
    (tmp_path / "market-memory-20261024T1805Z.json").write_text(text)
    out = M.load(tmp_path)
    assert out["entries"] == [] and out["sources"][0]["state"] == "error"


@pytest.mark.parametrize("cap", [10 ** 400, "1e400"])
def test_an_overflowing_or_infinite_number_in_a_run_file_gives_no_rows(tmp_path, cap):
    run = _sample()
    run["artifacts"]["goal"]["cap"] = cap
    (tmp_path / "run-a.json").write_text(json.dumps(run))
    out = M.load(tmp_path)
    assert out["entries"] == [] and json.dumps(out, allow_nan=False)


@pytest.mark.parametrize("field,value", [("amount_cents", 1), ("idempotency_key", "mandate:other")])
def test_a_demo_charge_for_another_amount_or_mandate_is_not_a_purchase(field, value):
    run = _sample()
    run["artifacts"]["charge"][field] = value
    assert not [e for e in M.from_demo_run(run, "r") if e["kind"] == "purchase"]


def test_an_approval_for_another_mandate_is_not_a_purchase():
    run = _sample()
    run["artifacts"]["approval_record"]["mandate_hash"] = "other"
    assert not [e for e in M.from_demo_run(run, "r") if e["kind"] == "purchase"]


def test_a_nan_payment_is_not_a_purchase():
    t = dict(MARKET, payment=[['"h1"', '"ch_test_1"', "nan", "2026-10-24T18:02:05+00:00", '"sim"']])
    assert not [e for e in M.from_market(fake_sql(t), "m") if e["kind"] == "purchase"]



@pytest.mark.parametrize("change", ["failed_charge", "no_hash"])
def test_a_failed_charge_or_a_mandate_with_no_hash_is_not_a_purchase(change):
    run = _sample()
    a = run["artifacts"]
    if change == "failed_charge":
        a["charge"]["status"] = "failed"
    else:
        a["mandate"]["hash"] = None
        a["approval_record"]["mandate_hash"] = None
        a["charge"]["idempotency_key"] = "mandate:None"
    assert not [e for e in M.from_demo_run(run, "r") if e["kind"] == "purchase"]
