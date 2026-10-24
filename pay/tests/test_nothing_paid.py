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
    calls = re.compile(r"""(?:def\s+approve_typed\b|\.call\(\s*["']approve_typed["']|\bapprove_typed\()""")   # a real call, not the name in a sentence)
    for folder in ("pay", "demo", "agents"):
        for f in (root / folder).rglob("*.py"):
            if "tests" in f.parts or f.name.startswith("test_"):
                continue
            assert not calls.search(f.read_text(encoding="utf-8")), f
