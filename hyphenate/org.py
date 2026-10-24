"""People, roles, permissions and the money policy. Limits live here, in code, not in a prompt."""
from __future__ import annotations

from dataclasses import dataclass, field

PERMISSIONS = {
    "employee": {"request"},
    "dept_head": {"request", "approve", "reject"},
    "controller": {"request", "approve", "reject", "close_period", "verify_bank_change"},
    "it_receiver": {"receive"},
    "vendor_admin": {"change_vendor_bank"},
    # the two seats Hyphenate fills: they prepare and match and pay what people approved; they approve nothing
    "purchasing_agent": {"draft_po", "replan"},
    "ap_agent": {"match", "post_bill", "release_payment", "reconcile"},
}
SYSTEM_ROLES = ("purchasing_agent", "ap_agent")


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str
    dept: str = ""
    acts_for: tuple = ()  # delegations: ids this person may act for

    def can(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, set())

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role, "dept": self.dept, "acts_for": list(self.acts_for),
                "system": self.role in SYSTEM_ROLES}


@dataclass(frozen=True)
class Policy:
    dept_head_limit: int = 250_000  # cents: a department head approves up to $2,500
    new_vendor_controller_over: int = 100_000  # first PO with an unproven vendor above $1,000 goes to the controller
    price_tol_pct: float = 0.005  # a price variance this small (or under tol_abs) is immaterial
    price_tol_abs: int = 100  # $1.00 per line
    mirror_above_pct: float = 0.15  # PO price more than 15% over a fresh MIRROR reference needs the controller
    mirror_below_pct: float = 0.40  # more than 40% under it looks like a trap
    duplicate_window_days: int = 60
    max_replans: int = 2
    serialized_skus_default: bool = True


def standard_people() -> list:
    """Pixel Forge Games, a 40-person game studio (SIM). Tony Stark is the requester, as in the Tech Bazaar demo."""
    return [
        Person("tony", "Tony Stark", "employee", "engineering"),
        Person("tony-assistant", "Pepper's Assistant", "employee", "engineering", acts_for=("tony",)),
        Person("rhodey", "James Rhodes", "dept_head", "engineering"),
        Person("kara", "Kara Danvers", "dept_head", "art"),
        Person("pepper", "Pepper Potts", "controller", "finance"),
        Person("happy", "Happy Hogan", "it_receiver", "it"),
        Person("maria", "Maria Hill", "vendor_admin", "finance"),
        Person("purchasing-agent", "Hyphenate Purchasing Agent (SIM)", "purchasing_agent", "it"),
        Person("ap-agent", "Hyphenate AP Clerk Agent (SIM)", "ap_agent", "finance"),
    ]


STANDARD_BUDGETS = {"engineering": 1_200_000, "art": 600_000, "it": 300_000}  # cents, one quarter, SIM
