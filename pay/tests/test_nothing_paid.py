"""#185: approval is by phone call only. A failed, unanswered or timed-out call pays nothing, and the buyer is told so
in one plain line. There is no typed fallback anywhere in pay/."""
from pathlib import Path

import pytest

from pay import approval, voice_cartesia as vc

PAY = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("reason, line", [
    ("call_failed", "Call failed, nothing was paid."),
    ("call_timeout", "The call timed out, nothing was paid."),
    ("no_answer:dial_no_answer", "No answer on the call, nothing was paid."),
    ("no_answer:voicemail_detected", "No answer on the call, nothing was paid."),
    ("no_transcript", "Nobody spoke on the call, nothing was paid."),
    ("no_buyer_speech", "Nobody spoke on the call, nothing was paid."),
    ("silence", "Nobody spoke on the call, nothing was paid."),
    ("wrong_code", "Not approved on the call, nothing was paid."),
    ("no_code", "Not approved on the call, nothing was paid."),
    ("max_attempts", "Not approved on the call, nothing was paid."),
    ("expired", "The deal expired before it was approved, nothing was paid."),
    ("not_configured: missing CARTESIA_API_KEY", "The call could not be placed, nothing was paid."),
    ("anything else", "Not approved, nothing was paid."),
    (None, "Not approved, nothing was paid."),
])
def test_every_denial_has_one_plain_nothing_was_paid_line(reason, line):
    assert vc.denial_line(reason) == line
    assert "—" not in line and "–" not in line


def test_a_denied_voice_result_carries_the_line_and_an_approved_one_none():
    assert vc.VoiceResult(False, "call_failed").buyer_line == "Call failed, nothing was paid."
    assert vc.VoiceResult(True, None).buyer_line is None


def test_there_is_no_typed_approval_path():
    assert not hasattr(approval.ApprovalSession, "approve_typed")
    for f in PAY.glob("*.py"):
        assert "approve_typed" not in f.read_text(encoding="utf-8"), f.name


def test_the_approval_session_has_exactly_the_known_public_methods():
    """#222: a new public method on the session (a second way to approve) fails here first."""
    public = sorted(n for n in dir(approval.ApprovalSession) if not n.startswith("_"))
    assert public == ["approve", "begin_listening", "silence", "start_call", "terminal", "tick", "to_record"]


def test_no_code_in_pay_demo_or_agents_calls_or_defines_a_typed_approval():
    """#222: scan pay/, demo/ and agents/ for a call or definition of approve_typed (the bridge may name it in text,
    to refuse a market that still has it, but must never call it)."""
    import re
    root = PAY.parent
    for folder in ("pay", "demo", "agents"):
        for f in (root / folder).rglob("*"):
            if f.suffix not in (".py", ".js", ".mjs", ".ts", ".tsx") or "node_modules" in f.parts:
                continue
            if "tests" in f.parts or f.name.startswith("test_") or ".test." in f.name:
                continue
            assert not TYPED_CALL.search(f.read_text(encoding="utf-8", errors="replace")), f


# #300: a real call or definition of the typed approval, however it is spelled; never the name in a sentence or the
# bridge's `"approve_typed" in module_text` check that refuses a market which still has it
TYPED_CALL = __import__("re").compile(
    r"""def\s+approve_typed\b|function\s+approveTyped\b|\bapprove_?[tT]yped\("""
    r"""|\.call\(\s*["']approve_typed["']|getattr\([^)]*["']approve_typed["']"""
    r"""|=\s*["']approve_typed["']|["']approve_["']\s*\+|\.approveTyped\b""")


@pytest.mark.parametrize("line", [
    "m.approve_typed(code)", "def approve_typed(self):", 'getattr(m, "approve_typed")(1)', "fn = getattr(market, 'approve_typed')",
    'NAME = "approve_typed"', 'referee.call(NAME := "approve_typed")', 'name = "approve_" + "typed"', 'client.call("approve_typed", code)',
    "await conn.reducers.approveTyped({ code })", "approveTyped(code)", "export function approveTyped(ctx) {",
])
def test_the_typed_approval_scan_catches_every_spelling(line):
    assert TYPED_CALL.search(line), line


@pytest.mark.parametrize("line", [
    'return "approve_typed" in module.read_text(encoding="utf-8")',
    'raise GateRefused("the market still has approve_typed (typed-code approval), so no code goes to /buyer")',
    "# approve_typed was removed in #185",
])
def test_the_typed_approval_scan_allows_the_name_in_text_and_the_refusal_check(line):
    assert not TYPED_CALL.search(line), line
