"""Owner-chat approvals record through the REFEREE (market.ts record_approval is referee-only) and carry the issued code (#455)."""
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
    """The market as the real reducers behave: record_approval is referee-only, and the referee reads its own agent_approvals
    view (main's module has no buyer-private purchase view). `require_code` models #455: the market compares the code with the
    one it issued for this mandate."""

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
                assert role == "referee" and "FROM agent_approvals" in query and "my_purchase_status" not in query
                if world.approval is None:
                    return []
                a = world.approval
                return [{"mandateHash": a["mandate_hash"], "method": a["method"], "approvedBy": a["approved_by"],
                         "at": "2026-10-25T10:00:00Z", "voiceApprovalId": a["voice_approval_id"]}]
        return Client()


@pytest.fixture(autouse=True)
def _clean():
    OA.ISSUED_CODES.clear()
    yield
    OA.ISSUED_CODES.clear()


def test_the_old_path_really_fails_on_the_live_rules_and_the_referee_path_records():
    world = World()
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), MarketBridge("referee", client=world.client("referee"))
    with pytest.raises(MarketBridgeError):  # what main did: record through the buyer identity
        buyer.record_approval(mandate_hash=HASH, method="voice_code", approved_by="vidyut", voice_approval_id="va-1", code="amber falcon")
    assert world.approval is None
    OA.remember_code(HASH, "amber falcon")
    status = OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert status["method"] == "voice_code" and world.approval["approved_by"] == "vidyut"
    assert world.approval["code"] == "amber falcon"
    assert [r for role, r, _ in world.calls if role == "referee"] == ["record_approval"]


def test_the_referee_bridge_requires_the_code_so_a_relay_without_one_sends_nothing():
    world = World()
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), MarketBridge("referee", client=world.client("referee"))
    assert OA.accepts_code(referee.record_approval)
    with pytest.raises(MarketBridgeError, match="approval_binding_invalid"):
        referee.record_approval(mandate_hash=HASH, method="voice_code", approved_by="vidyut", voice_approval_id="va-1")
    with pytest.raises(MarketBridgeError):  # no code remembered for this mandate: the relay fails closed before any call
        OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert world.approval is None and not [c for c in world.calls if c[1] == "record_approval"]
    OA.remember_code(HASH, "amber falcon")
    OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert world.approval["code"] == "amber falcon" and world.approval["voice_approval_id"] == "va-1"
    assert HASH not in OA.ISSUED_CODES  # one call, one code


def test_shape_after_455_the_issued_code_is_passed_and_the_market_checks_it():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), MarketBridge("referee", client=world.client("referee"))
    assert OA.accepts_code(referee.record_approval)
    world.client("referee").call("issue_approval_code", mandate_hash=HASH, code="amber falcon")
    OA.remember_code(HASH, "amber falcon")
    status = OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert world.approval["code"] == "amber falcon" and status["method"] == "voice_code"


def test_after_455_without_the_issued_code_nothing_is_recorded_and_nothing_can_be_paid():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), MarketBridge("referee", client=world.client("referee"))
    with pytest.raises(MarketBridgeError):  # no code remembered (e.g. an agent restart mid-call): fail closed
        OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert world.approval is None


def test_a_wrong_code_is_refused_by_the_market_and_never_accepted_as_recorded():
    world = World(require_code=True)
    buyer, referee = MarketBridge("buyer", client=world.client("buyer")), MarketBridge("referee", client=world.client("referee"))
    world.client("referee").call("issue_approval_code", mandate_hash=HASH, code="amber falcon")
    OA.remember_code(HASH, "other words")
    with pytest.raises(MarketBridgeError):
        OA.record_owner_approval(referee, MANDATE, "vidyut", "va-1")
    assert world.approval is None


def test_no_payment_unless_the_markets_own_row_shows_this_exact_mandate_approved():
    row = {"mandate_hash": HASH, "method": "voice_code", "approved_by": "vidyut", "at": "2026-10-25T10:00:00Z",
           "voice_approval_id": "va-1"}

    class Referee:
        def __init__(self, **o):
            self.o = o

        def record_approval(self, **kw):
            return {"approval_method": "voice_code"}

        def approval_row(self, h):
            return None if self.o.get("none") else {**row, **self.o}

    for override in ({"none": True}, {"method": "allowance"}, {"at": ""}, {"mandate_hash": "b" * 64},
                     {"approved_by": "mallory"}, {"voice_approval_id": "va-2"}):
        with pytest.raises(MarketBridgeError, match="market_approval_readback_mismatch"):
            OA.record_owner_approval(Referee(**override), MANDATE, "vidyut", "va-1")
    assert OA.record_owner_approval(Referee(), MANDATE, "vidyut", "va-1")["mandate_hash"] == HASH


def test_a_retry_after_the_write_landed_is_accepted_only_if_the_market_row_matches():
    row = {"mandate_hash": HASH, "method": "voice_code", "approved_by": "vidyut", "at": "2026-10-25T10:00:00Z",
           "voice_approval_id": "va-1"}

    class Referee:
        current = row

        def record_approval(self, **kw):
            raise MarketBridgeError("market_reducer_failed")

        def approval_row(self, h):
            return self.current

    assert OA.record_owner_approval(Referee(), MANDATE, "vidyut", "va-1") == row
    Referee.current = None
    with pytest.raises(MarketBridgeError, match="market_reducer_failed"):
        OA.record_owner_approval(Referee(), MANDATE, "vidyut", "va-1")
    Referee.current = dict(row, approved_by="mallory")
    with pytest.raises(MarketBridgeError, match="market_reducer_failed"):
        OA.record_owner_approval(Referee(), MANDATE, "vidyut", "va-1")


def test_the_code_is_remembered_in_memory_only_and_bounded():
    OA.remember_code(HASH, "amber falcon")
    assert OA.ISSUED_CODES == {HASH: "amber falcon"}
    for i in range(80):
        OA.remember_code(f"{i:064d}", "x y")
    assert len(OA.ISSUED_CODES) <= 64
    OA.remember_code(HASH, "")  # an empty code is never stored
    assert OA.ISSUED_CODES.get(HASH) != ""
