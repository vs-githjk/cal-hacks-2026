import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from pay.tap import keyring
from shield.api import create_app
from shield.product import KeyStore, Meter, create_product_app
from shield.registry import Registry


PAYEE = "seller-agent-1"
REQUEST = json.dumps({"accepted_funds": [{"amount": "749.00", "currency": "USD", "payment_method": "stripe"}],
                      "recipient": PAYEE, "deadline_seconds": 600, "reference": "hash-1",
                      "description": "deal deal-1"}, separators=(",", ":"))


def payload(request_json=REQUEST, payee=PAYEE):
    return {"message_id": "msg-1", "sender_agent": PAYEE, "request_json": request_json,
            "expected": {"deal_id": "deal-1", "mandate_hash": "hash-1", "amount_cents": 74900,
                         "currency": "USD", "payee": payee}}


def test_screen_payment_returns_receipt_for_exact_allowed_request():
    private = Ed25519PrivateKey.generate()
    registry = Registry(agents=[{"address": PAYEE, "name": "seller", "role": "seller", "seller_of_record": "seller"}])
    client = TestClient(create_app(registry=registry, receipt_private_key=private))
    response = client.post("/v1/shield/screen-payment", json=payload())
    assert response.status_code == 200 and response.json()["verdict"] == "allow"
    receipt = response.json()["receipt"]
    from shield.receipt import verify_allow_receipt
    result = verify_allow_receipt(receipt, keyring(private.public_key()), message_id="msg-1", request_json=REQUEST,
                                  deal_id="deal-1", mandate_hash="hash-1", amount_cents=74900,
                                  currency="USD", payee=PAYEE)
    assert result


def test_screen_payment_refuses_binding_mismatch_without_receipt():
    private = Ed25519PrivateKey.generate()
    registry = Registry(agents=[{"address": PAYEE, "name": "seller", "role": "seller", "seller_of_record": "seller"}])
    client = TestClient(create_app(registry=registry, receipt_private_key=private))
    response = client.post("/v1/shield/screen-payment", json=payload(payee="other-seller"))
    assert response.status_code == 200 and response.json()["verdict"] != "allow"
    assert "receipt" not in response.json()


def test_missing_signer_keeps_screening_operational_without_receipt():
    registry = Registry(agents=[{"address": PAYEE, "name": "seller", "role": "seller", "seller_of_record": "seller"}])
    client = TestClient(create_app(registry=registry, receipt_private_key=None))
    response = client.post("/v1/shield/screen-payment", json=payload())
    assert response.status_code == 200 and response.json()["verdict"] == "allow"
    assert "receipt" not in response.json()


def test_payment_receipt_route_is_keyed_metered_and_rate_limited(tmp_path):
    private = Ed25519PrivateKey.generate()
    registry = Registry(agents=[{"address": PAYEE, "name": "seller", "role": "seller", "seller_of_record": "seller"}])
    keys = KeyStore(tmp_path / "keys.json")
    key = keys.new("checkout")
    client = TestClient(create_product_app(keys=keys, meter=Meter(tmp_path / "meter.sqlite"), per_minute=1))
    assert client.post("/v1/shield/screen-payment", json=payload()).status_code == 401
    # The product wrapper uses the default app; verify the route is covered by the same key gate/rate/meter.
    client = TestClient(create_product_app(keys=keys, meter=Meter(tmp_path / "meter2.sqlite"), per_minute=1))
    headers = {"X-API-Key": key}
    assert client.post("/v1/shield/screen-payment", json=payload(), headers=headers).status_code == 200
    assert client.post("/v1/shield/screen-payment", json=payload(), headers=headers).status_code == 429
    assert client.get("/v1/usage", headers=headers).json()["calls"]["/v1/shield/screen-payment"] == 1


def test_legacy_screen_contract_is_unchanged():
    client = TestClient(create_app())
    body = client.post("/v1/shield/screen", json={"message_id": "legacy", "sender_agent": "x", "text": "RTX"}).json()
    assert {"verdict", "rule_ids", "message_id", "sender_agent", "reasons", "attack_type"} <= set(body)
    assert "receipt" not in body


def test_bad_configured_receipt_key_fails_app_startup_without_leaking_path(monkeypatch):
    monkeypatch.setenv("SHIELD_RECEIPT_PRIVATE_KEY_PATH", "private-receipt-key.pem")
    monkeypatch.setenv("VISA_TAP_PRIVATE_KEY_PATH", "buyer-tap-key.pem")
    with pytest.raises(ValueError) as error:
        create_app()
    assert str(error.value) == "SHIELD_RECEIPT_PRIVATE_KEY_PATH is not a valid Ed25519 key file"
