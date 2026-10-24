"""Minimal Python bridge to the Tech Bazaar market (stdlib only). Lane A agents call reducers here.

The bridge is the single point of failure between the Python agents and SpacetimeDB; the Convex
fallback would keep the same function names.
"""
import json
import os
import urllib.error
import urllib.request

HOST = os.environ.get("SPACETIMEDB_HTTP", "http://127.0.0.1:3000")
DB = os.environ.get("SPACETIMEDB_DB", "tech-bazaar")
TOKEN_FILE = os.environ.get("SPACETIMEDB_TOKEN_FILE", "")  # one file per agent keeps its identity stable


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
    """One identity. Reuse the same token (token_file) for an agent so it stays the same seller."""

    def __init__(self, token_file=TOKEN_FILE):
        token = None
        if token_file and os.path.exists(token_file):
            token = open(token_file).read().strip()
        if not token:
            _, body = _post("/v1/identity")
            token = json.loads(body)["token"]
            if token_file:
                with open(token_file, "w") as f:
                    f.write(token)
        self.headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}

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
