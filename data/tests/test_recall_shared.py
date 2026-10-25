"""One recall matcher for the product (#412 item 3a): the advocate's recall path (agents/advocate/real_data.py) and the Recall
Checker Actor (data/recall_checker_actor/src/main.py) both call data.recall_checker.check_product, so one table of cases must
give the same verdict through both. Verdicts: veto (a full model match, same Ti/Super variant), caution (a similar model),
none, unverified. CPSC answers are SIM fixtures, no network."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))  # advocate.real_data, as the agents tests run it

from advocate import real_data  # noqa: E402
from data.tests.test_recall_actor import FakeActor, load  # noqa: E402
import asyncio  # noqa: E402

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)


def gpu_recall(brand, name):  # SIM fixture, not a real recall
    return [{"Title": f"{brand} Recalls {name} Graphics Cards (SIM fixture)", "RecallDate": "2026-02-03T00:00:00",
             "URL": "https://example.test/recall", "Products": [{"Name": f"{brand} {name} graphics card"}], "Manufacturers": []}]


LAPTOP = [{"Title": "MSI Recalls Gaming Laptop Due to Fire Hazard (SIM fixture)", "RecallDate": "2026-02-01T00:00:00", "URL": "u",
           "Products": [{"Name": "MSI Gaming Laptop with GeForce RTX graphics"}], "Manufacturers": []}]


def boom(url):
    raise TimeoutError("slow")


def serve(items):
    return lambda url: json.dumps(items).encode()


# (id, brand, sku the buyer asked for, CPSC fetch, verdict)
CASES = [
    ("same model, same variant", "MSI", "msi rtx 4070 super 12gb", serve(gpu_recall("MSI", "GeForce RTX 4070 Super")), "veto"),
    ("super bid, ti recall", "MSI", "msi rtx 4070 super 12gb", serve(gpu_recall("MSI", "GeForce RTX 4070 Ti")), "caution"),
    ("plain bid, ti recall", "MSI", "msi rtx 4070 12gb", serve(gpu_recall("MSI", "GeForce RTX 4070 Ti")), "caution"),
    ("ti bid, plain recall", "ASUS", "asus rtx 5070 ti 16gb", serve(gpu_recall("ASUS", "GeForce RTX 5070")), "caution"),
    ("ti bid, ti recall", "ASUS", "asus rtx 5070 ti 16gb", serve(gpu_recall("ASUS", "GeForce RTX 5070 Ti")), "veto"),
    ("a laptop recall naming GeForce is not a graphics card (#156)", "ASUS", "asus tuf gaming geforce rtx 5070 ti 16gb gddr7 oc edition",
     serve([{**LAPTOP[0], "Title": "ASUS Recalls ROG Strix G16 Gaming Laptop", "Products": [{"Name": "ASUS ROG Strix G16 Gaming Laptop with GeForce RTX graphics"}]}]), "none"),
    ("a card with no model in its name cannot be ruled out", "MSI", "msi rtx", serve(gpu_recall("MSI", "GeForce RTX 4070 Super")), "unverified"),
    ("a laptop recall is not a graphics card", "MSI", "msi rtx 4070 super 12gb", serve(LAPTOP), "none"),
    ("same brand, another card", "MSI", "msi rtx 4070 super 12gb", serve(gpu_recall("MSI", "GeForce RTX 3060")), "none"),
    ("nothing recalled", "MSI", "msi rtx 4070 super 12gb", serve([]), "none"),
    ("the lookup fails", "MSI", "msi rtx 4070 super 12gb", boom, "unverified"),
    ("the API answers with a non-list", "MSI", "msi rtx 4070 super 12gb", lambda u: b'{"a": 1}', "unverified"),
    ("the API answers with html", "MSI", "msi rtx 4070 super 12gb", lambda u: b"<html>", "unverified"),
    ("no brand", "", "rtx 4070 super 12gb", serve(gpu_recall("MSI", "GeForce RTX 4070 Super")), "unverified"),
]


def through_the_advocate(brand, sku, fetch, tmp_path):
    bid = {"id": "b1", "lines": [{"sku_spec": sku, "unit_price": 500, "quantity": 1}]}
    found, notes = real_data.recalls_for_bids([bid], fetch=fetch, now=NOW, cache_dir=tmp_path, rows=[])
    if found:
        return "caution" if found[0]["partial"] else "veto"
    return "unverified" if any(n["rule_id"] == "advocate.recall_unverified" for n in notes) else "none"


def through_the_actor(brand, sku, fetch, tmp_path, monkeypatch):
    actor = FakeActor({"brand": brand, "product": sku})
    mod = load(monkeypatch, actor, tmp_path)
    monkeypatch.setattr(mod, "fetch", fetch)
    asyncio.run(mod.main())
    status = actor.rows[0]["status"]
    return {"recalled": "veto", "possible": "caution", "none": "none", "unverified": "unverified"}[status]


@pytest.mark.parametrize("name,brand,sku,fetch,verdict", CASES, ids=[c[0] for c in CASES])
def test_the_advocate_and_the_actor_give_the_same_verdict(name, brand, sku, fetch, verdict, tmp_path, monkeypatch):
    advocate = through_the_advocate(brand, sku, fetch, tmp_path / "a")
    actor = through_the_actor(brand, f"{brand.lower()} {sku}".strip(), fetch, tmp_path / "b", monkeypatch)
    assert (advocate, actor) == (verdict, verdict), name
