import sys
import types


def _install_agent_runtime_stubs():
    uagents = types.ModuleType("uagents")

    class Protocol:
        def __init__(self, *args, **kwargs):
            pass

        def on_message(self, *args, **kwargs):
            return lambda function: function

    uagents.Agent = type("Agent", (), {})
    uagents.Context = type("Context", (), {})
    uagents.Model = type("Model", (), {})
    uagents.Protocol = Protocol
    sys.modules.setdefault("uagents", uagents)

    crypto = types.ModuleType("uagents.crypto")
    crypto.Identity = type("Identity", (), {})
    sys.modules.setdefault("uagents.crypto", crypto)

    modules = {
        "uagents_core": types.ModuleType("uagents_core"),
        "uagents_core.contrib": types.ModuleType("uagents_core.contrib"),
        "uagents_core.contrib.protocols": types.ModuleType("uagents_core.contrib.protocols"),
    }
    for name, module in modules.items():
        module.__path__ = []
        sys.modules.setdefault(name, module)

    chat = types.ModuleType("uagents_core.contrib.protocols.chat")
    chat.ChatAcknowledgement = type("ChatAcknowledgement", (), {})
    chat.ChatMessage = type("ChatMessage", (), {})
    chat.TextContent = type("TextContent", (), {})
    chat.chat_protocol_spec = object()
    sys.modules.setdefault(chat.__name__, chat)

    payment = types.ModuleType("uagents_core.contrib.protocols.payment")
    for name in ("CommitPayment", "CompletePayment", "RejectPayment", "Funds", "RequestPayment"):
        setattr(payment, name, type(name, (), {}))
    payment.payment_protocol_spec = object()
    sys.modules.setdefault(payment.__name__, payment)


_install_agent_runtime_stubs()

from agents.sellers import seller_agent
from agents.sellers.policy import seller as load_seller


def _loss(report_id="loss-1", seller_id="seller-a", *, won=False, band="within10"):
    return {"id": report_id, "round_id": "round-1", "seller_id": seller_id, "won": won,
            "gap_band": band, "reason": "price", "source_url": "https://shop.example/item/1",
            "created_at": "2026-10-24T10:00:00Z"}


class _Reports:
    def __init__(self, rows):
        self.rows = rows

    def my_loss_reports(self):
        return self.rows


def _use_reports(monkeypatch, rows):
    monkeypatch.setenv("SPACETIMEDB_SELLER_A_TOKEN_FILE", "unused-test-path")
    monkeypatch.setattr(seller_agent, "MarketBridge", lambda *args, **kwargs: _Reports(rows), raising=False)


def _sim_seller():
    value = load_seller("seller_1")
    value["listings"]["gpu"] = {"price": 100.0, "floor": 0.0, "condition": "new",
                                 "page_condition": "new", "variant": "retail",
                                 "listing_url": "https://example.com/sim/gpu", "attrs": {}}
    return value


def _need(source="sim"):
    return {"id": "need-1", "source": source,
            "items": [{"sku_spec": "gpu", "condition": "new", "allowed_conditions": ["new"],
                       "quantity": 1}]}


def _db_path(tmp_path):
    return tmp_path / ".state" / "state.sqlite3"


def test_sim_bid_uses_composed_learned_discount_without_mutating_seller(monkeypatch, tmp_path):
    _use_reports(monkeypatch, [_loss()])
    seller = _sim_seller()

    bid = seller_agent._make_bid_with_learning(_need(), seller, "seller_1", _db_path(tmp_path))

    assert bid["lines"][0]["unit_price"] == 90.21
    assert seller["discount"] == 0.03


def test_foreign_winner_malformed_and_duplicate_rows_do_not_override_own_loss(monkeypatch, tmp_path):
    own = _loss()
    rows = [_loss("foreign", "seller-b", band="over20"), _loss("winner", won=True, band="over20"),
            {**_loss("malformed", band="over20"), "buyer_cap": 1}, own,
            {**own, "gap_band": "over20"}]
    _use_reports(monkeypatch, rows)
    seller = _sim_seller()

    bid = seller_agent._make_bid_with_learning(_need(), seller, "seller_1", _db_path(tmp_path))

    assert bid["lines"][0]["unit_price"] == 90.21


def test_learned_strategy_is_reused_after_database_reopen(monkeypatch, tmp_path):
    seller = _sim_seller()
    path = _db_path(tmp_path)
    _use_reports(monkeypatch, [_loss()])
    first = seller_agent._make_bid_with_learning(_need(), seller, "seller_1", path)
    monkeypatch.setattr(seller_agent, "MarketBridge", lambda *args, **kwargs: _Reports([]), raising=False)

    second = seller_agent._make_bid_with_learning(_need(), seller, "seller_1", path)

    assert first["lines"][0]["unit_price"] == 90.21
    assert second["lines"][0]["unit_price"] == 90.21


def test_sim_bid_keeps_existing_floor_clamp_after_learning(monkeypatch, tmp_path):
    _use_reports(monkeypatch, [_loss()])
    seller = _sim_seller()
    seller["listings"]["gpu"]["floor"] = 95.0

    bid = seller_agent._make_bid_with_learning(_need(), seller, "seller_1", _db_path(tmp_path))

    assert bid["lines"][0]["unit_price"] == 95.0
    assert bid["floor_check_passed"] is True


def test_mirror_bid_ignores_learned_discount(monkeypatch, tmp_path):
    _use_reports(monkeypatch, [_loss()])
    seller = _sim_seller()
    seller["listings"] = {}
    seller["mirror_listings"] = [{"id": "mirror-1", "origin": "MIRROR", "category": "gpu",
        "attrs": {"chipset": "gpu"}, "condition": "new", "price": 50.0, "source": "https://shop.example/gpu",
        "snapshot_id": "snap-1", "snapshot_date": "2026-10-24", "listing": {"stock": True},
        "seller_of_record": "Shop"}]
    seller["mirror_inputs"] = {"mirror-1": {
        "floor": {"origin": "MIRROR", "value": 40.0, "source": "https://shop.example/gpu", "observed_at": "2026-10-24T10:00:00Z"},
        "shipping": {"origin": "MIRROR", "value": 0.0, "source": "https://shop.example/gpu", "observed_at": "2026-10-24T10:00:00Z"}}}

    bid = seller_agent._make_bid_with_learning(_need("live"), seller, "seller_1", _db_path(tmp_path))

    assert bid["origin"] == "MIRROR"
    assert bid["lines"][0]["unit_price"] == 50.0
    assert seller["discount"] == 0.03


def test_market_publication_carries_exact_existing_listing_url(monkeypatch):
    captured = {}

    class _Publisher:
        def __init__(self, *args, **kwargs):
            pass

        def publish_bid(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("SPACETIMEDB_SELLER_A_TOKEN_FILE", "unused-test-path")
    monkeypatch.setattr(seller_agent, "MarketBridge", _Publisher)
    original_url = "https://example.com/sim/byte-bros/gpu"
    bid = {"supplier_id": "seller_1", "id": "bid-1", "need_id": "need-1", "persona": "Byte Bros",
           "lines": [{"sku_spec": "gpu", "unit_price": 90.21, "quantity": 1, "origin": "SIM",
                      "source": "simulated", "listing_url": original_url, "attrs": {}}],
           "total_landed_price": 90.21, "perks": [], "claims": [], "origin": "SIM", "source": "simulated"}

    seller_agent._market_bid(bid, {"shipping": 0.0})

    assert captured["line_metadata"][0]["provenance"]["listing_url"] == original_url
