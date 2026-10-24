"""#94: parseable status lines for Lane D's live agent feed (:8790), which tails agent logs.

    AGENT_STATUS name=<name> role=<role> address=<agent1q...> mode=mailbox|local
    AGENT_MSG name=<name> to=<name> text=<label>

The feed is public on our screens, so `text` is never a message body: it is a fixed label chosen by the
message kind. Approval codes, credentials, goals, caps and seller text cannot reach the feed through it.
`name`, `to` and `role` are single tokens; producer lines are at most 140 characters."""
import re

# Message kind -> the only text the feed may show for it.
LABELS = {
    "goal": "new goal received",
    "bid_request": "sealed request for bids",
    "bid": "bid submitted",
    "advice_request": "advocate review requested",
    "advice": "advocate cards returned",
    "order": "order placed, payment requested",
    "payment_request": "payment requested",
    "payment_commit": "payment committed",
    "payment_complete": "payment acknowledged",
    "payment_reject": "payment rejected",
    "reply": "reply to owner",
    "blocked": "message blocked by Shield",
}
ROLES = ("buyer", "advocate", "seller", "shield", "owner")
_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,40}")
_ADDRESS = re.compile(r"agent1q[0-9a-z]{20,80}")
_MAX_LINE_LENGTH = 140
_SDK_LINE = re.compile(r"^(?:\w+:\s+)?\[[^\]]+\]:\s+(AGENT_STATUS|AGENT_MSG) (.+)$")
_STATUS = re.compile(r"AGENT_STATUS name=([A-Za-z0-9_.-]{1,40}) role=(buyer|advocate|seller|shield|owner) "
                     r"address=(agent1q[0-9a-z]{20,80}) mode=(mailbox|local)$")
_MESSAGE = re.compile(r"AGENT_MSG name=([A-Za-z0-9_.-]{1,40}) to=([A-Za-z0-9_.-]{1,40}) text=(.+)$")


def _token(value: str, field: str) -> str:
    v = re.sub(r"\s+", "_", str(value).strip())
    if not _TOKEN.fullmatch(v):
        raise ValueError(f"{field} must be one short token, got {value!r}")
    return v


def status_line(name: str, role: str, address: str, mailbox: bool) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not _ADDRESS.fullmatch(address):
        raise ValueError("address must be an agent1q... address")
    line = (f"AGENT_STATUS name={_token(name, 'name')} role={role} address={address} "
            f"mode={'mailbox' if mailbox else 'local'}")
    if len(line) > _MAX_LINE_LENGTH:
        raise ValueError(f"status line exceeds {_MAX_LINE_LENGTH} characters")
    return line


def msg_line(name: str, to: str, kind: str) -> str:
    """`kind` must be a key of LABELS; anything else is refused rather than echoed."""
    if kind not in LABELS:
        raise ValueError(f"unknown message kind {kind!r}")
    line = f"AGENT_MSG name={_token(name, 'name')} to={_token(to, 'to')} text={LABELS[kind]}"
    if len(line) > _MAX_LINE_LENGTH:
        raise ValueError(f"message line exceeds {_MAX_LINE_LENGTH} characters")
    return line


def parse_line(line: str) -> dict | None:
    """Parse one SDK-prefixed producer line; reject embedded or malformed markers."""
    if not isinstance(line, str) or len(line) > _MAX_LINE_LENGTH + 160:
        return None
    m = _SDK_LINE.fullmatch(line)
    if not m:
        return None
    kind, body = m.groups()
    if kind == "AGENT_STATUS":
        parsed = _STATUS.fullmatch(f"{kind} {body}")
        if not parsed:
            return None
        name, role, address, mode = parsed.groups()
        return {"type": kind, "name": name, "role": role, "address": address, "mode": mode}
    parsed = _MESSAGE.fullmatch(f"{kind} {body}")
    if not parsed:
        return None
    name, to, text = parsed.groups()
    if text not in LABELS.values():
        return None
    return {"type": kind, "name": name, "to": to, "text": text}
