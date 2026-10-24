"""#261: UCP (draft spec 2026-01-11, not certified) on each Seller Kit shop. TestClient only, no network."""
import pytest
from fastapi.testclient import TestClient

from pay.mandate import new_mandate
from seller_kit import api, ucp
from seller_kit.tests.test_api import good

SHOP = "corner-pc"


@pytest.fixture
def client(tmp_path):
    c = TestClient(api.create_app(custom_dir=tmp_path / "custom"))
    assert c.post("/v1/sellers", json=good()).status_code == 201
    return c


def session(client, items=None):
    r = client.post(f"/ucp/{SHOP}/checkout-sessions", json={"line_items": items or [{"item": {"id": "rtx 5070 ti"}, "quantity": 1}]})
    return r


def mandate_for(s, **over):
    args = {"deal_id": s["id"], "buyer_id": "vidyut", "amount": next(t["amount"] for t in s["totals"] if t["type"] == "total") / 100,
            "payee": ucp.payee_for(SHOP), "origin": "SIM"}
    args.update(over)
    return new_mandate(**args)


def pay(m, handler=ucp.HANDLER_ID):
    return {"payment": {"instrument": {"handler_id": handler, "credential": {"mandate": m}}}}


def test_the_profile_declares_the_version_the_checkout_capability_and_the_phone_approval_handler(client):
    p = client.get(f"/ucp/{SHOP}/.well-known/ucp").json()
    assert p["ucp"]["version"] == "2026-01-11"
    assert [c["name"] for c in p["ucp"]["capabilities"]] == ["dev.ucp.shopping.checkout"]
    assert p["ucp"]["services"]["dev.ucp.shopping"]["rest"]["endpoint"].endswith(f"/ucp/{SHOP}")
    assert p["payment"]["handlers"][0]["name"] == "dev.techbazaar.phone_approval"
    assert p["tech_bazaar"]["label"] == "UCP draft spec 2026-01-11, not certified" and p["tech_bazaar"]["origin"] == "SIM"


def test_an_unknown_shop_or_a_path_trick_is_404(client):
    for shop in ("nope", "..", "corner-pc.json", "%2e%2e"):
        assert client.get(f"/ucp/{shop}/.well-known/ucp").status_code == 404


def test_a_session_is_priced_at_the_list_price_in_cents_and_never_shows_the_floor(client):
    r = session(client)
    s = r.json()
    assert r.status_code == 201 and s["status"] == "ready_for_complete" and s["currency"] == "USD"
    assert s["line_items"][0]["item"]["price"] == 130000
    assert {t["type"]: t["amount"] for t in s["totals"]} == {"subtotal": 130000, "fulfillment": 0, "total": 130000}
    assert "1200" not in str(s) and "floor" not in str(s).lower()
    assert s["tech_bazaar"]["origin"] == "SIM" and s["ucp"]["version"] == "2026-01-11"


@pytest.mark.parametrize("items, code", [
    ([{"item": {"id": "rtx 9999"}, "quantity": 1}], "item_unavailable"),
    ([{"item": {"id": "rtx 5070 ti"}, "quantity": 0}], "invalid_quantity"),
    ([{"item": {"id": "rtx 5070 ti"}, "quantity": True}], "invalid_quantity"),
    ([{"item": {"id": "rtx 5070 ti"}, "quantity": 11}], "invalid_quantity"),
    ([{"item": {}}], "invalid_item"),
    ("x", "invalid_line_items"),
])
def test_bad_line_items_leave_the_session_incomplete_with_a_message(client, items, code):
    r = client.post(f"/ucp/{SHOP}/checkout-sessions", json={"line_items": items})
    assert r.status_code == 201 and r.json()["status"] == "incomplete" and r.json()["messages"][0]["code"] == code


def test_update_retotals_and_get_reads_back(client):
    s = session(client).json()
    r = client.put(f"/ucp/{SHOP}/checkout-sessions/{s['id']}", json={"line_items": [{"item": {"id": "rtx 5070 ti"}, "quantity": 2}]})
    assert r.status_code == 200 and {t["type"]: t["amount"] for t in r.json()["totals"]}["total"] == 260000
    assert client.get(f"/ucp/{SHOP}/checkout-sessions/{s['id']}").json()["line_items"][0]["quantity"] == 2


def test_complete_with_a_mandate_for_this_session_holds_the_order_and_moves_no_money(client):
    s = session(client).json()
    m = mandate_for(s)
    r = client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/complete", json=pay(m))
    out = r.json()
    assert r.status_code == 200 and out["status"] == "complete_in_progress"
    assert out["order"] == {"mandate_hash": m["hash"], "mandate_id": m["id"], "settlement": "tech_bazaar_pay_after_phone_approval",
                            "money_moved_here": False, "origin": "SIM"}
    assert "completed" not in str(out).replace("complete_in_progress", "") and "paid" not in out["messages"][0]["content"].lower().replace("no money", "")


@pytest.mark.parametrize("change", ["amount", "payee", "deal", "tampered", "expired", "handler", "missing"])
def test_complete_refuses_any_mandate_not_for_exactly_this_session(client, change):
    s = session(client).json()
    if change == "amount":
        body = pay(mandate_for(s, amount=1.0))
    elif change == "payee":
        body = pay(mandate_for(s, payee="shady-sam@pay.example.test"))
    elif change == "deal":
        body = pay(mandate_for(s, deal_id="cs_other"))
    elif change == "tampered":
        m = mandate_for(s)
        m["payee"] = "x@pay.example.test"
        body = pay(m)
    elif change == "expired":
        from datetime import datetime, timedelta, timezone
        body = pay(mandate_for(s, now=datetime.now(timezone.utc) - timedelta(hours=1)))
    elif change == "handler":
        body = pay(mandate_for(s), handler="stripe")
    else:
        body = {}
    r = client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/complete", json=body)
    assert r.status_code == 402 and r.json()["status"] == "ready_for_complete" and "order" not in r.json(), change


def test_an_incomplete_or_canceled_session_cannot_complete(client):
    bad = client.post(f"/ucp/{SHOP}/checkout-sessions", json={"line_items": [{"item": {"id": "rtx 9999"}}]}).json()
    assert client.post(f"/ucp/{SHOP}/checkout-sessions/{bad['id']}/complete", json={}).status_code == 409
    s = session(client).json()
    assert client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/cancel").json()["status"] == "canceled"
    assert client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/complete", json=pay(mandate_for(s))).status_code == 409


def test_a_held_order_cannot_be_canceled_and_another_shop_cannot_read_a_session(client, tmp_path):
    s = session(client).json()
    client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/complete", json=pay(mandate_for(s)))
    assert client.post(f"/ucp/{SHOP}/checkout-sessions/{s['id']}/cancel").status_code == 409
    client.post("/v1/sellers", json=good(id="other-shop", name="Other Shop"))
    assert client.get(f"/ucp/other-shop/checkout-sessions/{s['id']}").status_code == 404


def test_bad_bodies_are_400_not_500(client):
    for body in (b"not json", b"[1, 2]", b"\xff\xfe"):
        r = client.post(f"/ucp/{SHOP}/checkout-sessions", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 400, body


def test_sessions_expire_and_the_store_is_capped(monkeypatch):
    shop = {"id": "s", "name": "S", "listings": {"x": {"price": 10.0}}, "pricing": {"mode": "discount"}, "shipping": 0}
    clock = [1000.0]
    store = ucp.Sessions(clock=lambda: clock[0])
    _, s = store.create(shop, {"line_items": [{"item": {"id": "x"}}]})
    clock[0] += ucp.SESSION_TTL_S + 1
    assert store.get(shop, s["id"]) is None
    monkeypatch.setattr(ucp, "MAX_SESSIONS", 2)
    assert [store.create(shop, {"line_items": [{"item": {"id": "x"}}]})[0] for _ in range(3)] == [201, 201, 503]


def test_the_buyer_object_keeps_only_a_short_name_and_email(client):
    r = client.post(f"/ucp/{SHOP}/checkout-sessions", json={"line_items": [{"item": {"id": "rtx 5070 ti"}}],
                                                           "buyer": {"full_name": "V" * 500, "email": "v@example.test", "card": "4242"}})
    assert r.json()["buyer"] == {"full_name": "V" * 120, "email": "v@example.test"}
