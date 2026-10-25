"""Startup self-check for the Market identity token files (Maincloud mode only).

A seller with a Market identity (seller_1, seller_2, seller_3) publishes its bid through its own token file, and the
Buyer needs a buyer file and a referee file. When one of those is not configured the failure used to be silent: the
seller logged an exception type and sent no reply, and the Buyer saw zero bids for three rounds. These helpers turn
that into one loud line that names the missing VARIABLE NAME. They read only the names and whether the file exists;
they never open a token file and never print a value, a path or a key.

Pure functions with no uagents import, so scripts/launch.py and the agents can both use them.
"""
from __future__ import annotations

import os
from typing import Callable, Mapping

# seller agent name -> the env var holding its token file (agents/sellers/seller_agent.py _MARKET_SELLER_SUBJECT)
SELLER_TOKEN_VARS = {"seller_1": "SPACETIMEDB_SELLER_A_TOKEN_FILE",
                     "seller_2": "SPACETIMEDB_SELLER_B_TOKEN_FILE",
                     "seller_3": "SPACETIMEDB_SELLER_C_TOKEN_FILE"}
BUYER_TOKEN_VARS = ("SPACETIMEDB_BUYER_TOKEN_FILE", "SPACETIMEDB_REFEREE_TOKEN_FILE")


def is_maincloud(env: Mapping[str, str]) -> bool:
    """True when SPACETIMEDB_SERVER names Maincloud ("maincloud" or a maincloud host), not a local market."""
    return "maincloud" in str(env.get("SPACETIMEDB_SERVER") or "").strip().lower()


def problems(variables, env: Mapping[str, str], exists: Callable[[str], bool] = os.path.isfile) -> list[str]:
    """For each variable: 'NAME is not set' or 'NAME points at a file that does not exist'. Names only."""
    out = []
    for var in variables:
        value = str(env.get(var) or "").strip()
        if not value:
            out.append(f"{var} is not set")
        elif not exists(value):
            out.append(f"{var} points at a file that does not exist")
    return out


def seller_line(name: str, env: Mapping[str, str], exists: Callable[[str], bool] = os.path.isfile) -> str | None:
    """One loud line when a Maincloud seller with a Market identity lacks its token file; None when fine or not applicable."""
    var = SELLER_TOKEN_VARS.get(name)
    if var is None or not is_maincloud(env):
        return None
    found = problems([var], env, exists)
    if not found:
        return None
    return (f"MARKET IDENTITY MISSING: {name} cannot publish bids to the Market ({found[0]}). Its bids will not reach "
            f"the Buyer. Set {var} to this seller's token file and restart the seller bureau.")


def buyer_line(env: Mapping[str, str], exists: Callable[[str], bool] = os.path.isfile) -> str | None:
    """One loud line when a Maincloud Buyer lacks its buyer or referee token file; None when fine or not applicable."""
    if not is_maincloud(env):
        return None
    found = problems(BUYER_TOKEN_VARS, env, exists)
    if not found:
        return None
    return (f"MARKET IDENTITY MISSING: the Buyer cannot run Market rounds ({'; '.join(found)}). "
            f"Set {' and '.join(BUYER_TOKEN_VARS)} to two different token files and restart the Buyer.")


def all_problems(env: Mapping[str, str], exists: Callable[[str], bool] = os.path.isfile) -> list[str]:
    """Every missing token variable for the seller bureau and the Buyer together (the launcher's preflight)."""
    return problems([*SELLER_TOKEN_VARS.values(), *BUYER_TOKEN_VARS], env, exists)
