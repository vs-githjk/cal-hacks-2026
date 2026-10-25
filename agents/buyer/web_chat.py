"""Local web chat fallback for when ASI:One is down. Stdlib only.
Start buyer_agent.py first, then from agents/:  .venv/Scripts/python.exe buyer/web_chat.py  and open http://localhost:8080
The page posts to this server, which forwards to the buyer agent's REST endpoint (same-origin, so no CORS)."""
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUYER = os.getenv("BUYER_REST_URL", "http://localhost:8001/chat")
PORT = int(os.getenv("WEB_CHAT_PORT", "8080"))


def buyer_headers() -> dict:
    """Headers for the call to the buyer's REST chat; #449 RT-26: the bearer token too when BUYER_REST_TOKEN is set."""
    headers = {"Content-Type": "application/json"}
    token = (os.getenv("BUYER_REST_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


PAGE = b"""<!doctype html><meta charset=utf-8><title>Fish Market buyer</title>
<style>body{font:15px system-ui;max-width:720px;margin:2em auto;padding:0 16px}#log{white-space:pre-wrap}
.me{color:#555;margin-top:1em}.ag{background:#f3f3f3;padding:.5em;margin:.3em 0}form{display:flex;gap:8px}input{flex:1;padding:.5em}</style>
<h1>Fish Market buyer (local)</h1><div id=log></div>
<form id=f><input id=t autofocus placeholder="a GPU for 1440p under $800 by Friday. I already own a 750 W PSU"><button>Send</button></form>
<script>
const log=document.getElementById('log');
function add(c,s){const d=document.createElement('div');d.className=c;d.textContent=s;log.appendChild(d);scrollTo(0,1e9)}
function show(j){(j.replies||[]).forEach(r=>add('ag',r))}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();const t=document.getElementById('t');if(!t.value)return;
 add('me','you: '+t.value);const r=await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t.value})});
 t.value='';show(await r.json())};
setInterval(async()=>{try{show(await (await fetch('/poll')).json())}catch(e){}},1500);
</script>"""


class Handler(BaseHTTPRequestHandler):
    def _reply(self, body: bytes, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def _forward(self, data: bytes | None):
        req = urllib.request.Request(BUYER, data=data, method="POST" if data else "GET",
                                     headers=buyer_headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.read()
        except Exception as e:
            return ('{"replies": ["Buyer agent unreachable: %s"]}' % str(e).replace('"', "'")).encode()

    def do_GET(self):
        if self.path == "/poll":
            self._reply(self._forward(None))
        else:
            self._reply(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        self._reply(self._forward(self.rfile.read(int(self.headers.get("Content-Length", 0)))))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"web chat on http://localhost:{PORT} -> {BUYER}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
