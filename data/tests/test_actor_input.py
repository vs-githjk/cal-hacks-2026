"""The public Actor's simple input (one page plus plain-line claims), its run summary and the default run. apify is stubbed."""
import asyncio
import json
from pathlib import Path

from data.tests.test_actor_charge import load_main

SCHEMA = Path(__file__).resolve().parents[1] / "claim_check" / "actor" / ".actor" / "input_schema.json"


class FakeActor:
    def __init__(self, inp):
        self.inp, self.rows, self.kv, self.status, self.charges = inp, [], {}, [], 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_input(self):
        return self.inp

    async def push_data(self, row):
        self.rows.append(row)

    async def charge(self, event_name, count):
        self.charges += count

    async def get_value(self, key):
        return self.kv.get(key)

    async def set_value(self, key, value):
        self.kv[key] = value

    async def set_status_message(self, msg, is_terminal=None):
        self.status.append((msg, is_terminal))

    class log:
        warning = staticmethod(print)


def run_main(monkeypatch, inp, check):
    mod = load_main(monkeypatch)
    actor = FakeActor(inp)
    monkeypatch.setattr(mod, "Actor", actor)
    monkeypatch.setattr(mod, "check_claim", check)
    asyncio.run(mod.main())
    return actor


def test_plain_lines_on_one_page_become_claims_and_batch_claims_are_kept(monkeypatch):
    mod = load_main(monkeypatch)
    got = mod.claims_from({"listingUrl": " https://shop.example/p/1 ", "claimTexts": ["price $10", " ", "in stock"],
                           "claims": [{"id": "b1", "text": "new", "evidence_url": "https://other.example/p"}]})
    assert got == [{"id": "c1", "text": "price $10", "evidence_url": "https://shop.example/p/1"},
                   {"id": "c2", "text": "in stock", "evidence_url": "https://shop.example/p/1"},
                   {"id": "b1", "text": "new", "evidence_url": "https://other.example/p"}]
    assert mod.claims_from({"claimTexts": ["new"]}) == [] and mod.claims_from(None) == []


def test_the_default_input_checks_three_claims_on_a_real_page(monkeypatch):
    props = json.loads(SCHEMA.read_text())["properties"]
    inp = {k: v["prefill"] for k, v in props.items() if "prefill" in v}
    claims = load_main(monkeypatch).claims_from(inp)
    assert len(claims) == 3 and all(c["evidence_url"].startswith("https://www.canadacomputers.com/") for c in claims)


def test_a_run_writes_rows_a_summary_and_charges_only_verdicts(monkeypatch):
    verdicts = iter([("verified", "h"), ("false", "h"), ("unverified", "")])

    def check(c):
        res, h = next(verdicts)
        return {"result": res, "evidence_hash": h, "reason": "r"}
    actor = run_main(monkeypatch, {"listingUrl": "https://shop.example/p", "claimTexts": ["a", "b", "c"]}, check)
    assert [r["result"] for r in actor.rows] == ["verified", "false", "unverified"] and actor.charges == 2
    assert actor.kv["OUTPUT"]["summary"] == "3 claim(s): 1 verified, 1 false, 1 unverified"
    assert actor.status[-1] == ("3 claim(s): 1 verified, 1 false, 1 unverified", True)


def test_no_claims_ends_with_a_clear_message_and_no_rows(monkeypatch):
    actor = run_main(monkeypatch, {}, lambda c: {})
    assert actor.rows == [] and actor.charges == 0 and "No claims given" in actor.status[-1][0]
