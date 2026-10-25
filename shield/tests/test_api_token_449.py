"""#449 RT-26: shield.api has no auth. SHIELD_API_TOKEN is optional: unset, the core is open as before (our own agents,
loopback); set, every route except /v1/shield/health needs `Authorization: Bearer <token>`."""
import pytest
from fastapi.testclient import TestClient

from pay.replay import NonceStore
from shield.api import create_app

TOKEN = "t0ken-for-tests-1234567890"
MSG = {"message_id": "m1", "sender_agent": "hal", "text": "RTX 5070 Ti, $799"}
GOOD = {"Authorization": f"Bearer {TOKEN}"}


def client(token=TOKEN, **kw):
    return TestClient(create_app(keys={}, store=NonceStore(), api_token=token, **kw))


ROUTES = [("post", "/v1/shield/screen", MSG), ("post", "/screen", MSG), ("post", "/v1/shield/screen-payment", {}),
          ("post", "/v1/shield/verify-mandate", {}), ("post", "/v1/shield/verify-agent", {}),
          ("post", "/v1/advocate/reason", {}), ("get", "/v1/shield/rules", None), ("get", "/openapi.json", None),
          ("get", "/docs", None)]


def send(c, method, path, body, headers=None):
    return getattr(c, method)(path, headers=headers or {}, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_with_a_token_set_every_route_but_health_refuses_a_missing_or_wrong_bearer(method, path, body):
    c = client()
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"},
                    {"X-API-Key": TOKEN}, {"Authorization": f"Bearer {TOKEN}x"}, {"Authorization": b"Bearer \xc3\xa9"}):
        r = send(c, method, path, body, headers)
        assert r.status_code == 401, (path, headers)
        assert r.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in r.text


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_the_right_bearer_reaches_the_route(method, path, body):
    r = send(client(), method, path, body, GOOD)
    assert r.status_code != 401, path


def test_health_stays_open_so_a_probe_works_without_the_secret():
    r = client().get("/v1/shield/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_a_screen_with_the_token_returns_the_normal_verdict():
    r = client().post("/v1/shield/screen", json=MSG, headers=GOOD)
    assert r.status_code == 200 and r.json()["verdict"] == "allow"


def test_the_refusal_comes_before_the_body_is_read_even_for_a_huge_one():
    r = client().post("/v1/shield/screen", content=b"x" * (70 * 1024), headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_unset_or_blank_leaves_the_core_open_as_before(monkeypatch):
    monkeypatch.delenv("SHIELD_API_TOKEN", raising=False)
    assert TestClient(create_app(keys={}, store=NonceStore())).post("/v1/shield/screen", json=MSG).status_code == 200
    for blank in ("", "   "):
        assert client(blank).post("/v1/shield/screen", json=MSG).status_code == 200


def test_the_env_var_is_read_when_no_token_is_passed(monkeypatch):
    monkeypatch.setenv("SHIELD_API_TOKEN", TOKEN)
    c = TestClient(create_app(keys={}, store=NonceStore()))
    assert c.post("/v1/shield/screen", json=MSG).status_code == 401
    assert c.post("/v1/shield/screen", json=MSG, headers=GOOD).status_code == 200


def test_the_token_is_compared_in_constant_time():
    import inspect
    from shield import api
    assert "compare_digest" in inspect.getsource(api)


def test_the_keyed_product_does_not_need_the_core_token_on_top_of_its_own_keys(tmp_path, monkeypatch):
    """shield.product wraps a fresh core and has its own API keys; SHIELD_API_TOKEN guards the keyless core only."""
    from shield.product import KeyStore, Meter, create_product_app
    monkeypatch.setenv("SHIELD_API_TOKEN", TOKEN)
    keys = KeyStore(tmp_path / "keys.json")
    key = keys.new("tester")
    c = TestClient(create_product_app(keys=keys, meter=Meter(tmp_path / "m.sqlite"), per_minute=100))
    assert c.post("/v1/shield/screen", json=MSG, headers={"X-API-Key": key}).status_code == 200
    assert c.post("/v1/shield/screen", json=MSG).status_code == 401
