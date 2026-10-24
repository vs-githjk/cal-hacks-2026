"""Create agent identities and grant their roles. Run once per database, as the module owner
(the identity the spacetime CLI published with). Token files are local secrets: keep them out of git.

Usage: python3 market/scripts/setup_roles.py [token_dir]   (default .tokens/, gitignored)
"""
import os
import subprocess
import sys

from stdb import DB, Market

TOKENS = sys.argv[1] if len(sys.argv) > 1 else ".tokens"
SERVER = os.environ.get("SPACETIMEDB_SERVER", "local")

AGENTS = [  # token file name, role, subject id
    ("referee", "referee", "market"),
    ("buyer-joe", "buyer", "joe"),
    ("seller-a", "seller", "seller-a"),
    ("seller-b", "seller", "seller-b"),
    ("seller-c", "seller", "seller-c"),
]

os.makedirs(TOKENS, exist_ok=True)
for name, role, subject in AGENTS:
    agent = Market(token_file=os.path.join(TOKENS, f"{name}.json"))
    subprocess.run(
        ["spacetime", "call", "-s", SERVER, DB, "assign_role", f'"0x{agent.identity}"', f'"{role}"', f'"{subject}"'],
        check=True, capture_output=True,
    )
    print(f"{name}: {role} {subject}")
