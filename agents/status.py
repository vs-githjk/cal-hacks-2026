"""#94: parseable status lines for Lane D's live agent feed (:8790), which tails agent logs.

    AGENT_STATUS name=<name> role=<role> address=<agent1q...> mode=mailbox|local
    AGENT_MSG name=<name> to=<name> text=<label>

The feed is public on our screens, so `text` is never a message body: it is a fixed label chosen by the
message kind. Approval codes, credentials, goals, caps and seller text cannot reach the feed through it.
`name`, `to` and `role` are single tokens; `text` is the rest of the line, at most 80 characters."""
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
# Anchored to the logger prefix, so remote text inside a logged reason cannot forge a line.
_LINE = re.compile(r"^(?:\w+:\s+)?\[[^\]]+\]:\s+(AGENT_STATUS|AGENT_MSG) (.*)$")
_ADDRESS = re.compile(r"agent1q[0-9a-z]{20,80}")


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
    return (f"AGENT_STATUS name={_token(name, 'name')} role={role} address={address} "
            f"mode={'mailbox' if mailbox else 'local'}")


def msg_line(name: str, to: str, kind: str) -> str:
    """`kind` must be a key of LABELS; anything else is refused rather than echoed."""
    if kind not in LABELS:
        raise ValueError(f"unknown message kind {kind!r}")
    return f"AGENT_MSG name={_token(name, 'name')} to={_token(to, 'to')} text={LABELS[kind]}"


def parse_line(line: str) -> dict | None:
    """For the feed: the fields of one AGENT_STATUS or AGENT_MSG line at the start of a logger message, else None."""
    m = _LINE.match(line)
    if not m:
        return None
    kind, rest = m.groups()
    out = {"type": kind}
    if kind == "AGENT_MSG":
        rest, _, text = rest.partition(" text=")
        out["text"] = text.strip()[:80]
    for part in rest.split():
        k, _, v = part.partition("=")
        out[k] = v
    return out
