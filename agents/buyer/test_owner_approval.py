"""Owner-chat approvals record through the REFEREE (market.ts record_approval is referee-only), shape-compatible with #455."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # agents/ for common, market_bridge
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

import owner_approval as OA
from market_bridge import MarketBridge, MarketBridgeError

HASH = "a" * 64
MANDATE = {"hash": HASH, "id": "mandate-1", "deal_id": "deal-1", "amount": 582.0, "payee": "agent1qpayee"}
OPTION_NONE = {"none": []}


class World:
    """The market as the real reducers behave: record_approval is referee-only, the buyer reads its own purchase row.
    `require_code` models #455: the market compares the code with the one it issued for this mandate."""

    def __init__(self, require_code=False):
        self.require_code, self.issued, self.approval, self.calls = require_code, {}, None, []

    def client(self, role):
        world = self

        class Client:
            identity = f"identity-{role}"

            def call(self, reducer, **args):
                world.calls.append((role, reducer, dict(args)))
                if reducer == "issue_approval_code":
                    world.issued[args["mandate_hash"]] = args["code"]
                    return
                if reducer == "record_approval":
                    if role != "referee":
                        raise RuntimeError(f"record_approval needs referee; caller is {role} vidyut")
                    if world.require_code and (not args.get("code") or args["code"] != world.issued.get(args["mandate_hash"])):
                        raise RuntimeError("the code does not match the one issued")
                    world.approval = args

            def sql(self, query):
                assert role == "buyer" and "my_purchase_status" in query
                approved = world.approval is not None
                return [{"mandateHash": HASH, "mandateId": "mandate-1", "dealId": "deal-1", "goalId": "goal-1", "needId": "need-1",
                         "amount": 582.0, "payee": "agent1qpayee", "expiry": "2099-01-01T00:00:00Z", "origin": "SIM",
                         "withinAllowance": False, "retired": False, "reservationMatches": True, "settled": False,
                         "approvalMethod": {"some": "voice_code"} if approved else OPTION_NONE,
                         "approvedAt": {"some": "2026-10-25T10:00:00Z"} if approved else OPTION_NONE,
                         "paymentRef": OPTION_NONE, "paymentAmount": OPTION_NONE, "paymentMode": OPTION_NONE, "paidAt": OPTION_NONE}]
        return Client()


class BridgeWithoutCode(MarketBridge):
    """The referee bridge before #455: record_approval takes no `code` (with #455 merged, the real bridge takes one)."""

    def record_approval(self, *, mandate_hash, method, approved_by, voice_approval_id=""):
        self._call("record_approval", mandate_hash=mandate_hash, method=method, approved_by=approved_by,
                   voice_approval_id=voice_approval_id)
        return {"mandate_hash": mandate_hash, "approval_method": method}


class BridgeWithCode(MarketBridge):
    """The referee bridge after #455: record_approval takes the issued `code` and refuses to relay without it."""

    def record_approval(self, *, mandate_hash, method, approved_by, voice_approval_id="", code=""):
        if not voice_approval_id or not code.strip():
            raise MarketBridgeError("approval_binding_invalid")
        self._call("record_approval", mandate_hash=mandate_hash, method=method, approved_by=approved_by,
                   voice_approval_id=voice_approval_id, code=code)
        return {"mandate_hash": mandate_hash, "approval_method": method}


@pytest.fixture(autouse=True)
def _clean():
    OA.ISSUED_CODES.clear()
    yield
    OA.ISSUED_CODES.clear()


def simple_matches(status, mandate):
    return (status.get("mandate_hash") == mandate["hash"] and status.get("payee") == mandate["payee"]
            and float(status.get("amount")) == mandate["amount"] and bool(status.get("approved_at")) and not status.get("retired"))


def test_the_old_path_really_fails_on_the_live_rules_and_the_referee_path_records():
    world = World()
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), BridgeWithoutCode("referee", client=world.client("referee"))
    with pytest.raises(MarketBridgeError):  # what main did: record through the buyer identity
        buyer.record_approval(mandate_hash=HASH, method="voice_code", approved_by="vidyut", voice_approval_id="va-1")
    assert world.approval is None
    status = OA.record_owner_approval(referee, buyer, MANDATE, "vidyut", "va-1", simple_matches)
    assert status["approval_method"] == "voice_code" and world.approval["approved_by"] == "vidyut"
    assert [r for role, r, _ in world.calls if role == "referee"] == ["record_approval"]


def test_shape_before_455_the_bridge_takes_no_code_so_none_is_sent():
    world = World()
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), BridgeWithoutCode("referee", client=world.client("referee"))
    assert not OA.accepts_code(referee.record_approval)
    OA.remember_code(HASH, "amber falcon")
    OA.record_owner_approval(referee, buyer, MANDATE, "vidyut", "va-1", simple_matches)
    assert "code" not in world.approval and world.approval["voice_approval_id"] == "va-1"
    assert HASH not in OA.ISSUED_CODES  # one call, one code


def test_shape_after_455_the_issued_code_is_passed_and_the_market_checks_it():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), BridgeWithCode("referee", client=world.client("referee"))
    assert OA.accepts_code(referee.record_approval)
    world.client("referee").call("issue_approval_code", mandate_hash=HASH, code="amber falcon")
    OA.remember_code(HASH, "amber falcon")
    status = OA.record_owner_approval(referee, buyer, MANDATE, "vidyut", "va-1", simple_matches)
    assert world.approval["code"] == "amber falcon" and status["approval_method"] == "voice_code"


def test_after_455_without_the_issued_code_nothing_is_recorded_and_nothing_can_be_paid():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), BridgeWithCode("referee", client=world.client("referee"))
    with pytest.raises(MarketBridgeError):  # no code remembered (e.g. an agent restart mid-call): fail closed
        OA.record_owner_approval(referee, buyer, MANDATE, "vidyut", "va-1", simple_matches)
    assert world.approval is None


def test_a_wrong_code_is_refused_by_the_market_and_never_accepted_as_recorded():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), BridgeWithCode("referee", client=world.client("referee"))
    world.client("referee").call("issue_approval_code", mandate_hash=HASH, code="amber falcon")
    OA.remember_code(HASH, "other words")
    with pytest.raises(MarketBridgeError):
        OA.record_owner_approval(referee, buyer, MANDATE, "vidyut", "va-1", simple_matches)
    assert world.approval is None


def test_no_payment_unless_the_markets_own_row_shows_this_exact_mandate_approved():
    class Row:
        def __init__(self, **o):
            self.o = o

        def purchase_status(self, h):
            return {"approval_method": "voice_code", "approved_at": "2026-10-25T10:00:00Z", "mandate_hash": HASH,
                    "amount": 582.0, "payee": "agent1qpayee", "retired": False, **self.o}

    class Referee:
        def record_approval(self, **kw):
            return {"approval_method": "voice_code"}

    for override in ({"approval_method": None}, {"approved_at": None}, {"mandate_hash": "b" * 64}, {"payee": "agent1qother"},
                     {"amount": 1.0}, {"retired": True}):
        with pytest.raises(MarketBridgeError, match="market_approval_readback_mismatch"):
            OA.record_owner_approval(Referee(), Row(**override), MANDATE, "vidyut", "va-1", simple_matches)
    assert OA.record_owner_approval(Referee(), Row(), MANDATE, "vidyut", "va-1", simple_matches)["mandate_hash"] == HASH


def test_a_retry_after_the_write_landed_is_accepted_only_if_the_market_row_matches():
    class Referee:
        def record_approval(self, **kw):
            raise MarketBridgeError("market_reducer_failed")

    row = {"approval_method": "voice_code", "approved_at": "2026-10-25T10:00:00Z", "mandate_hash": HASH,
           "amount": 582.0, "payee": "agent1qpayee", "retired": False}

    class Buyer:
        status = row

        def purchase_status(self, h):
            return self.status

    assert OA.record_owner_approval(Referee(), Buyer(), MANDATE, "vidyut", "va-1", simple_matches) == row
    Buyer.status = dict(row, approval_method=None)
    with pytest.raises(MarketBridgeError, match="market_reducer_failed"):
        OA.record_owner_approval(Referee(), Buyer(), MANDATE, "vidyut", "va-1", simple_matches)


def test_the_code_is_remembered_in_memory_only_and_bounded():
    OA.remember_code(HASH, "amber falcon")
    assert OA.ISSUED_CODES == {HASH: "amber falcon"}
    for i in range(80):
        OA.remember_code(f"{i:064d}", "x y")
    assert len(OA.ISSUED_CODES) <= 64
    OA.remember_code(HASH, "")  # an empty code is never stored
    assert OA.ISSUED_CODES.get(HASH) != ""
