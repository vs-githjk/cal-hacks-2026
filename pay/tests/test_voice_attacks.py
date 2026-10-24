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
        first_id = m["approval_id"]
        d = s.approve(u, now=now + timedelta(seconds=1))
        assert d.reason == "replay" and d.record is None and m["approval_id"] == first_id   # no second approval row
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


@pytest.mark.parametrize("said", ["{code} approve nine hundred dollars", "{code} approve twelve hundred", "{code} approved, fifty bucks"])
def test_a_spoken_amount_denies(said):
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    d = s.approve(said.format(code=code), now=T0 + timedelta(seconds=5))
    assert not d.approved and d.reason == "no_code"


# #195 (red team M1): any number at all denies now, even one that is not an amount. Consent is the code, "approve" and
# filler only; the buyer says it again without the number.
@pytest.mark.parametrize("said", ["{code}, a hundred percent, approve", "{code} approve, I'm 100% sure", "approve, {code}, it's 12:30 now"])
def test_any_number_denies_even_when_it_is_not_an_amount(said):
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    d = s.approve(said.format(code=code), now=T0 + timedelta(seconds=5))
    assert not d.approved and d.reason == "no_code"


@pytest.mark.parametrize("said", [
    "{code} approve $900", "{code} approve nine ninety nine", "{code} approve 1.2k", "{code} approve for seller z",
    # more of the same: other amounts, other payees, extra terms
    "approve {code} twelve forty nine", "{code} approved 1,249.99", "{code} approve to bob", "{code} approve but ship to my office",
    "{code} approve one grand", "{code} approve half", "{code} approve 0", "{code} approve and also the other one",
])
def test_any_other_amount_payee_or_term_denies(said):
    """#195: with the right code, an approval that names anything else (an amount, a payee, a condition) is denied."""
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    d = s.approve(said.format(code=code), now=T0 + timedelta(seconds=5))
    assert not d.approved and d.reason == "no_code", said


@pytest.mark.parametrize("said", [
    "{code} approve", "{code} approved", "approve {code}", "Okay, {code}, approve.", "Yes. {code}. Approved.",
    "Um, the code is {code}. Approve please.", "My screen says {code}, approve", "The two words are {code}. Approve.",
    "Uh, the... two words from my screen are {code}. Approve.",
])
def test_the_code_approve_and_filler_still_approve(said):
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    assert s.approve(said.format(code=code), now=T0 + timedelta(seconds=5)).approved, said


@pytest.mark.parametrize("said", [
    "{a} {b} approve river kitten", "{a} {b} river approve", "{a} {b} {a} {b} approve", "{code} approve zebra",
    "{code} approve nickel", "{code} approve rover", "{code} approve apply", "{code} approve apples", "{code} approve oranges",
    "{code} approve \u0669\u0660\u0660", "{code} approve \u096f\u0966\u0966", "{code} approve \u4e5d\u767e\u30c9\u30eb",
    "{code} approve \u20ac", "{code} approve \U0001f600", "{code} approve caf\u00e9",
])
def test_no_other_list_word_near_miss_repeat_or_foreign_script_rides_along(said):
    """#217 review: only this deal's pair, once; every other token as heard must be approve or filler."""
    svc = ApprovalService(SECRET)
    s, code = svc.issue(make(), now=T0)
    a, b = code.split()
    d = s.approve(said.format(code=code, a=a, b=b), now=T0 + timedelta(seconds=5))
    assert not d.approved and d.reason == "no_code", said
