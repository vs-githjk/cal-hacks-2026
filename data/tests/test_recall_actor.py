"""The Electronics Recall Checker Actor (#271): its form, charging and summaries. apify is stubbed; CPSC answers are the real
fixtures read on Oct 24 2026; no network."""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

ACTOR = Path(__file__).resolve().parents[1] / "recall_checker_actor"
FIX = Path(__file__).resolve().parent / "fixtures"
SCHEMA = json.loads((ACTOR / ".actor" / "input_schema.json").read_text())["properties"]
FORM = {k: v["prefill"] for k, v in SCHEMA.items() if "prefill" in v}


def fixture_fetch(url):
    for brand in ("anker", "samsung"):
        if url.lower().endswith(brand):
            return (FIX / f"recalls_{brand}_real.json").read_bytes()
    return b"[]"


class FakeActor:
    def __init__(self, inp, limit=99, fail_charge=False):
        self.inp, self.rows, self.kv, self.status, self.charges = inp, [], {}, [], []
        self.limit, self.fail_charge = limit, fail_charge

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_input(self):
        return self.inp

    async def push_data(self, row):
        self.rows.append(row)

    async def get_value(self, k):
        return self.kv.get(k)

    async def set_value(self, k, v):
        self.kv[k] = v

    async def set_status_message(self, msg, is_terminal=None):
        self.status.append((msg, is_terminal))

    async def charge(self, event_name, count):
        if self.fail_charge:
            raise RuntimeError("charge endpoint down")
        self.charges.append(event_name)
        return types.SimpleNamespace(event_charge_limit_reached=len(self.charges) >= self.limit, charged_count=count)

    class log:
        warning = staticmethod(print)


def load(monkeypatch, actor, tmp_path):
    apify = types.ModuleType("apify")
    apify.Actor = actor
    monkeypatch.setitem(sys.modules, "apify", apify)
    spec = importlib.util.spec_from_file_location("recall_actor_main", ACTOR / "src" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "fetch", fixture_fetch)
    monkeypatch.setattr(mod, "CACHE", tmp_path)
    return mod


def run(monkeypatch, tmp_path, inp, **kw):
    actor = FakeActor(inp, **kw)
    asyncio.run(load(monkeypatch, actor, tmp_path).main())
    return actor


def test_the_default_form_finds_the_real_anker_and_samsung_recalls(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, FORM)
    by = {r["product"]: r for r in a.rows}
    assert by["PowerCore 10000 A1263"]["status"] == "recalled" and by["PowerCore 10000 A1263"]["recall_url"].startswith("https://www.cpsc.gov/Recalls/2025/")
    assert by["Galaxy Note7"]["status"] == "recalled" and by["Nano Charger 30W"]["status"] == "none"
    assert a.status[-1] == ("3 product(s): 2 recalled, 0 possible, 1 none, 0 unverified", True)
    assert a.charges == ["product-checked"] * 3 and a.kv["OUTPUT"]["checked"] == 3


def test_one_product_gives_its_own_summary(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, {"brand": "Anker", "product": "PowerCore 10000 A1263"})
    assert a.status[-1][0].startswith("RECALLED: Anker PowerCore 10000 A1263 matches 1 CPSC recall(s)")


def test_an_unverified_product_is_free(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, {"products": [" | product with no brand", "Anker | PowerCore 10000 A1263"]})
    assert [r["status"] for r in a.rows] == ["unverified", "recalled"] and a.charges == ["product-checked"]


def test_the_batch_lines_parse_brand_product_and_upc(monkeypatch, tmp_path):
    mod = load(monkeypatch, FakeActor({}), tmp_path)
    got = mod.products_from({"products": "Acme | Charger X1 | 841234567890\nSamsung | Galaxy Note7"})
    assert got == [{"id": "p1", "brand": "Acme", "product": "Charger X1", "upc": "841234567890"},
                   {"id": "p2", "brand": "Samsung", "product": "Galaxy Note7", "upc": None}]


def test_the_limit_stops_the_run_and_says_what_was_not_checked(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, FORM, limit=1)
    assert len(a.rows) == 1 and a.status[-1][0].endswith("2 not checked: your charge limit was reached")


def test_a_failed_charge_stops_and_delivers_nothing_unpaid(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, FORM, fail_charge=True)
    assert a.rows == [] and a.status[-1][0].endswith("3 not checked: the charge failed")


def test_a_paid_product_is_redelivered_on_restart_without_a_second_charge(monkeypatch, tmp_path):
    actor = FakeActor({"products": ["Anker | PowerCore 10000 A1263", "Samsung | Galaxy Note7"]})
    actor.kv["STATE_next_product"] = {"index": 0, "paid": True}
    asyncio.run(load(monkeypatch, actor, tmp_path).main())
    assert actor.charges == ["product-checked"] and len(actor.rows) == 2


def test_no_product_ends_with_a_clear_message(monkeypatch, tmp_path):
    a = run(monkeypatch, tmp_path, {})
    assert a.rows == [] and "No product given" in a.status[-1][0]


def test_the_fetch_only_calls_the_cpsc_api(monkeypatch):
    monkeypatch.setitem(sys.modules, "apify", types.SimpleNamespace(Actor=None))
    spec = importlib.util.spec_from_file_location("recall_actor_fetch", ACTOR / "src" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for url in ("https://evil.example/x", "http://www.saferproducts.gov/RestWebServices/Recall", "file:///etc/passwd"):
        try:
            mod.fetch(url)
            raise AssertionError(f"fetched {url}")
        except ValueError as e:
            assert "only the CPSC" in str(e)
