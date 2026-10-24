import json

from fastapi.testclient import TestClient

from hyphenate.api import create_app
from hyphenate.demo import run_story
from hyphenate.draft import draft_explanation
from hyphenate.engine import mirror_refs, seed_company

P = "/v1/hyphenate"


def client(story=None):
    c = TestClient(create_app(seed_company(mirror={}), demo_clock=True))
    if story:
        assert c.post(f"{P}/demo/reset?story={story}").json()["ok"]
    return c


def test_demo_story_has_the_moment_and_clean_books():
    r = run_story()
    assert r["invariants"] == [] and r["trial_balance"]["balanced"]
    labels = {s["label"]: s for s in r["steps"]}
    assert labels["Vidyut tries to self-approve the PO"]["status"] == "denied"
    assert labels["Pepper (controller) says no, ceiling $2,600"]["status"] == "replanned"
    assert labels["Invoice for 2 new units arrives, remit-to account changed"]["status"] == "held"
    assert labels["Payment attempt the next morning"]["status"] == "denied"
    assert labels["Stripe test record shows $5 more than the ledger"]["status"] == "corrected"
    assert "qty_short" in r["explain"]["text"] and "remit_to_mismatch" in r["explain"]["text"] and r["explain"]["chain"]


def test_mirror_reference_ignores_sold_history_and_uses_the_median():
    refs = mirror_refs()
    assert 100_000 < refs["RTX-5070-TI"]["price"] < 150_000  # the $640 sold-listing outlier no longer sets it
    assert refs["RTX-5070-TI"]["origin"] == "MIRROR" and "median" in refs["RTX-5070-TI"]["source"]
    assert mirror_refs("/nonexistent/path") == {}


def test_api_full_flow_and_refusals_are_results_not_errors():
    c = client()
    r = c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2026-10-24T09:00:00Z", "lines": [{"sku": "SSD-2TB", "qty": 2, "price": 100.0}]}).json()
    po = r["po"]["id"]
    assert r["ok"] and r["po"]["route"]["needs"] == ["dept_head"]
    no = c.post(f"{P}/pos/{po}/approve", json={"by": "vidyut", "at": "2026-10-24T10:00:00Z"})
    assert no.status_code == 200 and no.json()["ok"] is False and no.json()["code"] == "self_approval"
    ok = c.post(f"{P}/pos/{po}/approve", json={"by": "rhodey", "at": "2026-10-24T11:00:00Z"}).json()
    assert ok["ok"] and ok["po"]["status"] == "approved"
    rc = c.post(f"{P}/pos/{po}/receive", json={"by": "happy", "at": "2026-10-25T09:00:00Z", "lines": [{"sku": "SSD-2TB", "qty": 2, "condition": "new", "serials": ["a", "b"]}]}).json()
    assert rc["ok"]
    iv = c.post(f"{P}/invoices", json={"po_id": po, "number": "X1", "date": "2026-10-26", "at": "2026-10-26T09:00:00Z", "lines": [{"sku": "SSD-2TB", "qty": 2, "price": 100.0}]}).json()
    iid = iv["invoice"]["id"]
    pay = c.post(f"{P}/invoices/{iid}/pay", json={"at": "2026-10-27T09:00:00Z"}).json()
    assert pay["ok"] and pay["payment"]["amount"] == 20000
    tb = c.get(f"{P}/ledger/trial-balance").json()
    assert tb["balanced"] and tb["subledger_problems"] == []
    last = pay["decision_ids"][-1]
    x = c.get(f"{P}/audit/{last}/explain").json()
    assert x["text"] and x["journal_entries"]
    assert c.get(f"{P}/audit/verify").json()["broken"] == []
    rec = c.get(f"{P}/reconciliation").json()["rows"][0]
    assert rec["ledger"] == 20000 and rec["bank"] is None and rec["believed"] == "ledger"


def test_api_errors_404_409_422_and_body_limit():
    c = client()
    assert c.get(f"{P}/pos/PO-9").status_code == 404
    assert c.get(f"{P}/audit/dec_9999/explain").status_code == 404
    assert c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2026-10-24T09:00:00Z", "lines": [{"sku": "x", "qty": 0, "price": 1}]}).status_code == 422
    c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2026-10-24T09:00:00Z", "lines": [{"sku": "x", "qty": 1, "price": 1}]})
    assert c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2026-10-23T09:00:00Z", "lines": [{"sku": "x", "qty": 1, "price": 1}]}).status_code == 409
    assert c.post(f"{P}/requisitions", content=b"x" * 70_000, headers={"content-type": "application/json"}).status_code == 413


def test_api_moment_reset_and_lists():
    c = client("moment")
    assert len(c.get(f"{P}/pos").json()["pos"]) == 2
    assert len(c.get(f"{P}/invoices?status=superseded").json()["invoices"]) == 1  # the held bill was replaced by the corrected one
    assert c.get(f"{P}/memos").json()["memos"]
    assert any(a["id"] == "2100" for a in c.get(f"{P}/ledger/accounts").json()["accounts"])
    assert c.get(f"{P}/vendors").json()["vendors"][0]["risk"]["level"]
    assert c.get(f"{P}/audit?kind=invoice_match").json()["total"] == 1 and c.get(f"{P}/audit?kind=bill_posting").json()["total"] == 1
    assert c.get(f"{P}/company").json()["origin"] == "SIM"
    assert c.post(f"{P}/demo/reset?story=bogus").status_code == 422


def test_api_results_runs_the_planted_sets_live():
    body = client().get(f"{P}/results").json()
    assert body["label"] == "SIM" and body["dev"]["missed"] == [] and body["held_out"]["missed"] == []


def test_draft_is_template_offline_and_model_text_with_invented_numbers_is_discarded():
    x = run_story()["explain"]
    assert draft_explanation(x, llm=lambda p: None)["source"] == "template"
    good = draft_explanation(x, llm=lambda p: f"Held. {x['decision']['id']} says no.")
    assert good["source"] == "model"
    bad = draft_explanation(x, llm=lambda p: "Held, and the loss is $9,999.99 on PO-7777.")
    assert bad["source"] == "template" and bad["text"] == x["text"]
    # an outcome word the record does not contain ("paid") is discarded even with correct ids and amounts
    lie = draft_explanation(x, llm=lambda p: f"{x['decision']['id']} was paid in full.")
    assert lie["source"] == "template"


def test_client_supplied_time_is_ignored_on_a_server_clock_app():
    c = TestClient(create_app(seed_company(mirror={})))
    r = c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2099-01-01T00:00:00Z", "lines": [{"sku": "x", "qty": 1, "price": 1}]}).json()
    assert r["po"]["created_at"] < "2099"  # the far-future `at` did not age anything out
    assert c.get(f"{P}/health").json()["clock_mode"] == "server"
    c.post(f"{P}/demo/reset?story=empty")
    assert c.get(f"{P}/health").json()["clock_mode"].startswith("demo")
    r2 = c.post(f"{P}/requisitions", json={"requester": "vidyut", "vendor_id": "bestbuy", "at": "2099-01-01T00:00:00Z", "lines": [{"sku": "x", "qty": 1, "price": 1}]}).json()
    assert r2["po"]["created_at"].startswith("2099")  # demo mode honours scripted timestamps


def test_requisition_route_ignores_a_dept_field():
    c = client()
    r = c.post(f"{P}/requisitions", json={"requester": "vidyut", "dept": "art", "vendor_id": "bestbuy", "at": "2026-10-24T09:00:00Z", "lines": [{"sku": "x", "qty": 1, "price": 1}]}).json()
    assert r["po"]["dept"] == "engineering"


def test_cors_allows_only_the_local_web_origin_for_get_and_post():
    c = client("moment")
    ok = c.get(f"{P}/pos", headers={"Origin": "http://localhost:3100"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:3100"
    assert c.get(f"{P}/pos", headers={"Origin": "http://127.0.0.1:3100"}).headers["access-control-allow-origin"] == "http://127.0.0.1:3100"
    pre = c.options(f"{P}/demo/reset", headers={"Origin": "http://localhost:3100", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 200 and "POST" in pre.headers["access-control-allow-methods"]
    for bad in ("https://evil.example", "http://localhost.evil.example", "http://evil.example:3100"):
        assert c.get(f"{P}/pos", headers={"Origin": bad}).headers.get("access-control-allow-origin") is None
        assert c.options(f"{P}/demo/reset", headers={"Origin": bad, "Access-Control-Request-Method": "POST"}).status_code == 400
    # no Origin header (the Python lanes) is untouched
    assert "access-control-allow-origin" not in c.get(f"{P}/pos").headers
