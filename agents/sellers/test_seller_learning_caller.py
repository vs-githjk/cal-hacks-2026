import asyncio
import json

from agents.buyer import state
from agents.sellers import seller_agent
from agents.sellers import learning
from agents.sellers.policy import make_bid as policy_make_bid, seller as load_seller


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


class _Protocol:
    def __init__(self, **_kwargs):
        self.handlers = {}

    def on_message(self, model):
        def register(handler):
            self.handlers[model] = handler
            return handler
        return register


class _Agent:
    def __init__(self, **_kwargs):
        self.address = "seller-agent-test"
        self.handlers = {}
        self.protocols = []

    def on_message(self, model):
        def register(handler):
            self.handlers[model] = handler
            return handler
        return register

    def include(self, protocol, **_kwargs):
        self.protocols.append(protocol)


class _Context:
    session = "offline-learning-test"

    def __init__(self, events):
        self.events = events
        self.sent = []
        self.logs = []
        self.logger = self

    async def send(self, to, message):
        self.events.append("reply")
        self.sent.append((to, message))

    def warning(self, message):
        self.logs.append(message)


def _registered_bid_handler(monkeypatch, seller):
    monkeypatch.setattr(seller_agent, "Agent", _Agent)
    monkeypatch.setattr(seller_agent, "Protocol", _Protocol)
    monkeypatch.setattr(seller_agent.common, "agent_args", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(seller_agent.common, "include_profile_chat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(seller_agent.common, "screen", lambda *_args, **_kwargs: {"verdict": "allow", "reasons": []})
    monkeypatch.setattr(seller_agent.common, "shield_context", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(seller_agent, "load_seller", lambda _name: seller)
    app = seller_agent.build("seller_1")
    return app.handlers[seller_agent.common.BidRequest]


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


def test_registered_bid_handler_fails_closed_when_learning_state_is_unavailable(monkeypatch):
    events = []
    handler = _registered_bid_handler(monkeypatch, _sim_seller())
    monkeypatch.delenv("SPACETIMEDB_SELLER_A_TOKEN_FILE", raising=False)
    monkeypatch.setattr(learning, "open_learning_state",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private state path")))
    monkeypatch.setattr(seller_agent, "make_bid", lambda *_args, **_kwargs: events.append("base-bid"))
    ctx = _Context(events)
    message = seller_agent.common.BidRequest(need_json=json.dumps(_need()))

    asyncio.run(handler(ctx, "buyer-test", message))

    assert not ctx.sent
    assert "base-bid" not in events
    assert ctx.logs == ["seller learning unavailable: OSError"]


def test_registered_bid_handler_applies_own_loss_before_building_and_sending_bid(monkeypatch, tmp_path):
    events = []
    seller = _sim_seller()
    db_path = _db_path(tmp_path)
    monkeypatch.setattr(state, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setenv("SPACETIMEDB_SELLER_A_TOKEN_FILE", "unused-test-path")

    class _LearningBridge:
        def __init__(self, *args, **kwargs):
            pass

        def my_loss_reports(self):
            events.append("reports")
            return [_loss()]

        def publish_bid(self, **_kwargs):
            events.append("publish")

    monkeypatch.setattr(seller_agent, "MarketBridge", _LearningBridge)
    original_make_bid = policy_make_bid

    def observe_strategy(need, bid_seller):
        db = learning.open_learning_state(db_path)
        try:
            step = learning.load_strategy(db, "seller-a")["price_step"]
        finally:
            db.close()
        events.append(("make_bid", step))
        return original_make_bid(need, bid_seller)

    monkeypatch.setattr(seller_agent, "make_bid", observe_strategy)
    handler = _registered_bid_handler(monkeypatch, seller)
    ctx = _Context(events)
    message = seller_agent.common.BidRequest(need_json=json.dumps(_need()))

    asyncio.run(handler(ctx, "buyer-test", message))

    assert events == ["reports", ("make_bid", 0.07), "publish", "reply"]
    assert len(ctx.sent) == 1
    bid = json.loads(ctx.sent[0][1].bid_json)
    assert bid["lines"][0]["unit_price"] == 90.21
