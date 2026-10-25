import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seed_floors as sf

CATALOG = json.loads(sf.SELLERS_JSON.read_text(encoding="utf-8"))


class FakeSeller:
    def __init__(self, name, log, fail=False):
        self.name, self.log, self.fail = name, log, fail

    def call(self, reducer, **args):
        if self.fail:
            raise RuntimeError("set_floor_for_condition failed (400): needs seller")
        self.log.append((self.name, reducer, args))


def test_plan_covers_every_catalog_floor_of_the_three_market_sellers():
    rows = sf.planned_floors(CATALOG)
    assert {r["seller"] for r in rows} == {"seller-a", "seller-b", "seller-c"}
    assert {"seller": "seller-a", "sku_spec": "rtx 5070 ti", "condition": "new", "floor": 1239.0} in rows
    assert {"seller": "seller-c", "sku_spec": "rtx 5070 ti", "condition": "new", "floor": 1209.0} in rows
    assert all(r["floor"] > 0 and r["condition"] in sf.CONDITIONS for r in rows)


def test_sku_filter_and_extra_floor_for_a_seller_with_no_listing():
    rows = sf.planned_floors(CATALOG, ["rtx 5070 ti"], ["seller-b=rtx 5070 ti:new:1189"])
    assert [(r["seller"], r["condition"], r["floor"]) for r in rows] == [("seller-a", "new", 1239.0), ("seller-c", "new", 1209.0),
                                                                        ("seller-b", "new", 1189.0)]


def test_a_later_floor_replaces_the_same_seller_sku_and_condition():
    rows = sf.planned_floors(CATALOG, ["rtx 5070 ti"], ["seller-a=rtx 5070 ti:new:1000"])
    assert [r["floor"] for r in rows if r["seller"] == "seller-a"] == [1000.0]


@pytest.mark.parametrize("bad", ["nope", "seller-z=gpu:new:5", "seller-a=gpu:mint:5", "seller-a=gpu:new:0", "seller-a=gpu:new:x"])
def test_bad_extra_floors_are_refused(bad):
    with pytest.raises(ValueError):
        sf.planned_floors(CATALOG, ["no such sku"], [bad])


def test_dry_run_writes_nothing_and_never_builds_a_client():
    lines, built = [], []
    failed = sf.apply_floors(sf.planned_floors(CATALOG), lambda s: built.append(s), write=False, say=lines.append)
    assert failed == 0 and built == [] and lines and all(x.startswith("DRY RUN") for x in lines)


def test_apply_calls_set_floor_for_condition_as_each_seller_and_is_repeatable():
    log = []
    rows = sf.planned_floors(CATALOG, ["rtx 5070 ti"])
    for _ in range(2):   # the reducer replaces the row, so a second run is the same calls
        assert sf.apply_floors(rows, lambda s: FakeSeller(s, log), write=True, say=lambda t: None) == 0
    assert len(log) == 4 and {c[1] for c in log} == {"set_floor_for_condition"}
    assert ("seller-a", "set_floor_for_condition", {"sku_spec": "rtx 5070 ti", "condition": "new", "floor": 1239.0}) in log


def test_a_refused_call_is_counted_and_the_rest_still_go():
    log, lines = [], []
    rows = sf.planned_floors(CATALOG, ["rtx 5070 ti"])
    failed = sf.apply_floors(rows, lambda s: FakeSeller(s, log, fail=(s == "seller-a")), write=True, say=lines.append)
    assert failed == 1 and [c[0] for c in log] == ["seller-c"] and any(x.startswith("FAILED") for x in lines)


def test_a_missing_token_file_is_an_error_not_a_new_identity(tmp_path):
    make = sf.market_client_for(tmp_path, "https://example.invalid", "x")
    with pytest.raises(FileNotFoundError):
        make("seller-a")
    assert list(tmp_path.iterdir()) == []


def test_main_defaults_to_a_dry_run_that_needs_no_tokens(capsys, tmp_path):
    assert sf.main(["--sku", "rtx 5070 ti", "--tokens-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN: 2 floors" in out and "nothing was written" in out and "SET " not in out
