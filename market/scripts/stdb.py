"""Minimal Python bridge to the Tech Bazaar market (stdlib only). Lane A agents call reducers here.

The bridge is the single point of failure between the Python agents and SpacetimeDB; the Convex
fallback would keep the same function names.
"""
import json
import os
import secrets
import urllib.error
import urllib.request

HOST = os.environ.get("SPACETIMEDB_HTTP", "http://127.0.0.1:3000")
DB = os.environ.get("SPACETIMEDB_DB", "tech-bazaar")
TOKEN_FILE = os.environ.get("SPACETIMEDB_TOKEN_FILE", "")  # one file per agent keeps its identity stable


# Crockford base32 (no I L O U), the same alphabet the market module accepts for a pairing code.
PAIR_CODE_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_pair_code():
    """#449 RT-2: a fresh pairing code, XXXXX-XXXXX, from the OS random source. The market module never makes one itself
    (its ctx.random is seeded from the public transaction time); the owner makes it here and sends it to reissue_pair_code,
    which stores only its sha256. Show it to the operator only; never log it."""
    raw = "".join(secrets.choice(PAIR_CODE_CHARS) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def _post(path, body=b"", headers=None):
    req = urllib.request.Request(HOST + path, data=body, method="POST", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _camel(name):
    head, *rest = name.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


class Market:
    """One identity. Reuse the same token_file for an agent so it keeps its identity and role.

    Roles (buyer, seller, referee) are granted by the module owner: run setup_roles.py once.
    """

    def __init__(self, token_file=TOKEN_FILE):
        saved = None
        if token_file and os.path.exists(token_file):
            saved = json.load(open(token_file))
        if not saved:
            _, body = _post("/v1/identity")
            saved = json.loads(body)
            if token_file:
                with open(token_file, "w") as f:
                    json.dump({"token": saved["token"], "identity": saved["identity"]}, f)
        self.identity = saved["identity"]
        self.headers = {"Authorization": "Bearer " + saved["token"], "Content-Type": "application/json"}

    def call(self, reducer, **args):
        """Call a reducer. Pass every name in snake_case (buyer_id, items=[{"sku_spec": ...}]).

        SpacetimeDB's HTTP API wants top-level reducer args in camelCase (as declared in index.ts)
        but nested object fields in snake_case, so this converts the top level for you.
        """
        wire = {_camel(k): v for k, v in args.items()}
        status, body = _post(f"/v1/database/{DB}/call/{reducer}", json.dumps(wire).encode(), self.headers)
        if status != 200:
            raise RuntimeError(f"{reducer} failed ({status}): {body}")

    def sql(self, query):
        status, body = _post(f"/v1/database/{DB}/sql", query.encode(), self.headers)
        if status != 200:
            raise RuntimeError(f"sql failed ({status}): {body}")
        return json.loads(body)[0]["rows"]
