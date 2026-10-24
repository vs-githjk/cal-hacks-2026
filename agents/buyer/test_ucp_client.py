"""#261: the buyer agent discovers a kit shop over UCP and checks out through it. The real Seller Kit app in-process
(TestClient), no network."""
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ucp_client as U  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from pay.mandate import new_mandate  # noqa: E402
from seller_kit import api  # noqa: E402
from seller_kit.tests.test_api import good  # noqa: E402

BASE = "http://testserver"


@pytest.fixture
def transport(tmp_path):
    tc = TestClient(api.create_app(custom_dir=tmp_path / "custom"))
    assert tc.post("/v1/sellers", json=good()).status_code == 201

    def send(method, url, body=None):
        parts = urlsplit(url)
        r = tc.request(method, parts.path, content=body, headers={"content-type": "application/json"} if body else {})
        return r.status_code, r.json()
    return send


def test_discover_create_and_complete_through_a_kit_shop(transport):
    shop = U.discover(f"{BASE}/ucp/corner-pc", transport=transport)
    assert shop["endpoint"] == f"{BASE}/ucp/corner-pc" and shop["payee"] == "corner-pc@pay.example.test"
    s = U.create_checkout(shop, [("rtx 5070 ti", 1)], transport=transport)
    assert U.total_dollars(s) == 1300.0
    m = new_mandate(deal_id=s["id"], buyer_id="vidyut", amount=U.total_dollars(s), payee=shop["payee"], origin="SIM")
    held = U.complete(shop, s, m, transport=transport)
    assert held["status"] == "complete_in_progress" and held["order"]["money_moved_here"] is False


def test_a_wrong_mandate_is_not_held(transport):
    shop = U.discover(f"{BASE}/ucp/corner-pc", transport=transport)
    s = U.create_checkout(shop, [("rtx 5070 ti", 1)], transport=transport)
    m = new_mandate(deal_id=s["id"], buyer_id="vidyut", amount=1.0, payee=shop["payee"], origin="SIM")
    with pytest.raises(U.UcpError, match="did not hold"):
        U.complete(shop, s, m, transport=transport)


def test_an_unknown_item_is_not_ready(transport):
    shop = U.discover(f"{BASE}/ucp/corner-pc", transport=transport)
    with pytest.raises(U.UcpError, match="not ready"):
        U.create_checkout(shop, [("rtx 9999", 1)], transport=transport)


def profile(**over):
    p = {"ucp": {"version": "2026-01-11", "services": {"dev.ucp.shopping": {"rest": {"endpoint": "https://shop.example.test/ucp/x"}}},
                 "capabilities": [{"name": "dev.ucp.shopping.checkout", "version": "2026-01-11"}]},
         "payment": {"handlers": [{"id": "h1", "name": "dev.techbazaar.phone_approval", "config": {"payee": "x@pay.example.test"}}]}}
    for k, v in over.items():
        if k == "version":
            p["ucp"]["version"] = v
        elif k == "endpoint":
            p["ucp"]["services"]["dev.ucp.shopping"]["rest"]["endpoint"] = v
        elif k == "caps":
            p["ucp"]["capabilities"] = v
        elif k == "handlers":
            p["payment"]["handlers"] = v
    return p


@pytest.mark.parametrize("over, why", [
    ({"version": "2025-01-01"}, "speaks"), ({"caps": []}, "checkout capability"),
    ({"endpoint": "https://evil.example.test/ucp/x"}, "another host"), ({"endpoint": "file:///etc/passwd"}, "http"),
    ({"handlers": [{"id": "h", "name": "com.stripe.card"}]}, "phone-approval"),
])
def test_discovery_refuses_a_profile_it_will_not_act_on(over, why):
    with pytest.raises(U.UcpError, match=why):
        U.discover("https://shop.example.test/ucp/x", transport=lambda m, u, b: (200, profile(**over)))


def test_discovery_refuses_a_non_http_shop_url_and_a_missing_profile():
    with pytest.raises(U.UcpError, match="http"):
        U.discover("ftp://shop.example.test", transport=lambda m, u, b: (200, profile()))
    with pytest.raises(U.UcpError, match="no UCP profile"):
        U.discover("https://shop.example.test/ucp/x", transport=lambda m, u, b: (404, {"messages": []}))
