"""Register a running mailbox agent on Agentverse with AGENTVERSE_API_KEY from agents/.env.
Start the agent first (e.g. BUYER_MAILBOX=1 python buyer/buyer_agent.py), then: python connect.py 8001"""
import json
import os
import sys
import urllib.request

import common  # noqa: F401  (loads agents/.env)

port = sys.argv[1] if len(sys.argv) > 1 else "8001"
body = json.dumps({"user_token": os.environ["AGENTVERSE_API_KEY"], "agent_type": "mailbox"}).encode()
req = urllib.request.Request(f"http://localhost:{port}/connect", data=body, method="POST",
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.read().decode())  # {"success": ..., "detail": ...}; never echoes the key
