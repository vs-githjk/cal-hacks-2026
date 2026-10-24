"""Hello milestone from Python (stdlib only): call a reducer, read the rows back."""
import json, os, urllib.request

HOST = os.environ.get("SPACETIMEDB_URI", "http://127.0.0.1:3000")
DB = os.environ.get("SPACETIMEDB_DB", "bidding-royale")

def post(path, body=b"", headers=None):
    req = urllib.request.Request(HOST + path, data=body, method="POST", headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read().decode()

_, ident = post("/v1/identity")
auth = {"Authorization": "Bearer " + json.loads(ident)["token"], "Content-Type": "application/json"}
print("call", post(f"/v1/database/{DB}/call/say_hello", json.dumps({"text": "hello from python", "price": 4.0}).encode(), auth))
status, rows = post(f"/v1/database/{DB}/sql", b"SELECT * FROM hello", auth)
print("sql", status, json.loads(rows)[0]["rows"])
