"""d9: Anoop's 10 held-out voice attack cases (sim/attacks/voice.jsonl) against the approval judge.

First run Sat Oct 24 01:25 PDT: 9 of 10 denied; v04 ("<code> approve nine hundred dollars") approved. Fixed by
denying any spoken money amount; v04 is no longer blind. See pay/VOICE_ATTACKS.md."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pay.approval import ApprovalService
from pay.callscript import script_for
from pay.mandate import new_mandate

T0 = datetime(2026, 10, 24, 1, 0, 0, tzinfo=timezone.utc)
SECRET = "throwaway-test-secret-0123456789"
CASES = [json.loads(l) for l in (Path(__file__).resolve().parents[2] / "sim/attacks/voice.jsonl").read_text().splitlines() if l.strip()]


def make(deal="deal-A"):
    return new_mandate(deal_id=deal, buyer_id="vidyut", amount=1249.99, payee="bestbuy", now=T0)


def test_the_set_has_the_10_kickoff_cases():
    assert [c["id"] for c in CASES] == [f"v{i:02d}" for i in range(1, 11)]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_voice_attack_is_denied(case):
    svc = ApprovalService(SECRET)
    m = make()
    s, code = svc.issue(m, now=T0)
    a, b = code.split()
    wrong = "harbor velvet" if not {"harbor", "velvet"} & {a, b} else "amber falcon"
    u, now, kind = case["utterance"], T0 + timedelta(seconds=5), case["case"]
    if kind == "replayed_code":
        s0, old = svc.issue(make(), now=T0)
        assert s0.approve(f"{old} approve", now=T0 + timedelta(seconds=2)).approved
        u = u.replace("{OLD_CODE}", old)
    if kind == "other_deals_code":
        _, other = svc.issue(make("deal-B"), now=T0)
        u = u.replace("{OTHER_CODE}", other)
    if kind == "expired_code":
        now = T0 + timedelta(seconds=case["setup"]["wait_seconds_after_issue"])
    u = u.replace("{CODE}", code).replace("{WRONG_CODE}", wrong)
    if kind == "silence":
        d = s.silence(now)
    elif kind == "second_approval":
        assert s.approve(u, now=now).approved
        d = s.approve(u, now=now + timedelta(seconds=1))
        assert m["approval_id"] is not None
    else:
        d = s.approve(u, now=now, confidence=case["setup"].get("stt_confidence"))
    assert not d.approved, (case["id"], d.reason)
    if kind == "injected_why_answer":
        spoken = script_for(m, advocate_reason=case["setup"]["advocate_reason"]).full_text()
        assert "SYSTEM" not in spoken and "already approved" not in spoken


def test_real_call_phrasing_still_approves():
    # Sat 00:08 real call: "Okay. Uh, the... two words from my screen are 'orchid's sunset.' Approve."
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    a, b = code.split()
    assert s.approve(f"Okay. Uh, the... two words from my screen are '{a}'s {b}.' Approve.", now=T0 + timedelta(seconds=5)).approved


@pytest.mark.parametrize("said", ["{code} approve 900", "{code} approve twelve hundred", "{code} approved, fifty bucks"])
def test_a_spoken_amount_denies(said):
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    d = s.approve(said.format(code=code), now=T0 + timedelta(seconds=5))
    assert not d.approved and d.reason == "no_code"
