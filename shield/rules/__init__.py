"""Rules as files: one module per rule family, each exposing Rule objects with a stable id."""
from shield.rules import encoded, exfil, hidden, impersonation, money, override, payee, price

RULES = [
    override.RULE,
    hidden.TEXT_RULE,
    hidden.INSTRUCTION_RULE,
    payee.RULE,
    money.RULE,
    price.RULE,
    exfil.RULE,
    encoded.RULE,
    impersonation.RULE,
]
RULES_BY_ID = {r.id: r for r in RULES}
