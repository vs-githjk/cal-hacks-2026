"""The allowlist registry for /v1/shield/verify-agent: SIM entries for our demo agents, plus a denylist.

An address that is not in `agents` is unregistered (quarantined). An address in `denylist` is blocked, and the
denylist wins over the allowlist. A malformed or duplicated registry raises RegistryError at startup instead of
quietly allowing anything.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registry.json")
ROLES = ("buyer", "advocate", "seller", "marketplace")


class RegistryError(ValueError):
    pass


@dataclass
class Registry:
    agents: list[dict] = field(default_factory=list)
    denylist: list[dict] = field(default_factory=list)
    origin: str = "SIM"

    def __post_init__(self):
        self._by_address: dict[str, dict] = {}
        for a in self.agents:
            if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and a.get(k) for k in ("address", "name", "role")):
                raise RegistryError("each agent needs a non-empty address, name and role")
            if a["role"] not in ROLES:
                raise RegistryError(f"unknown role {a['role']!r}")
            if a["role"] == "seller" and not (isinstance(a.get("seller_of_record"), str) and a["seller_of_record"]):
                raise RegistryError("a seller entry needs seller_of_record")
            if a["address"] in self._by_address:
                raise RegistryError(f"duplicate address {a['address']!r}")
            self._by_address[a["address"]] = a
        self._denied = {d["address"] for d in self.denylist if isinstance(d, dict) and isinstance(d.get("address"), str)}
        if len(self._denied) != len(self.denylist):
            raise RegistryError("each denylist entry needs an address")

    def get(self, address: str) -> Optional[dict]:
        return self._by_address.get(address)

    def is_denied(self, address: str) -> bool:
        return address in self._denied


def load_registry(path: Optional[str] = None) -> Registry:
    path = path or os.environ.get("SHIELD_REGISTRY") or DEFAULT_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise RegistryError(f"cannot read registry {os.path.basename(path)}: {type(e).__name__}") from e
    if not isinstance(data, dict) or not isinstance(data.get("agents"), list) or not isinstance(data.get("denylist", []), list):
        raise RegistryError("registry must be an object with an agents list and a denylist list")
    return Registry(agents=data["agents"], denylist=data.get("denylist", []), origin=str(data.get("origin", "SIM")))
