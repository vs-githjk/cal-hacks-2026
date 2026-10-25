"""Paired screenshots for demo/rehearse.py --screens (#184).

`chrome --screenshot` starts a fresh profile every time, so /buyer always showed the pair gate. Here the rehearsal pairs
ONE screen identity of its own through the market's real `pair_buyer_screen` reducer, with a code it makes itself and the owner
issues (#449 RT-2: the market keeps only a hash; never printed, never logged, entered once: five misses lock the screen). That identity's token then goes into one
headless Chrome's localStorage over the DevTools protocol, and every screenshot is taken in that same browser.

Stdlib only: a minimal WebSocket client for the DevTools protocol (no new dependency). The token never leaves this
process and the browser it starts; the browser's profile is a temp dir removed on close.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome",
)
DEMO_BUYER = "vidyut"


def find_chrome() -> Optional[str]:
    """CHROME_PATH, else Google Chrome on macOS, else a chrome or chromium on PATH, else the sandbox Chromium."""
    for c in (os.environ.get("CHROME_PATH"), CHROME_CANDIDATES[0], shutil.which("google-chrome"), shutil.which("chromium"),
              shutil.which("chromium-browser"), *CHROME_CANDIDATES[1:]):
        if c and Path(c).exists():
            return c
    return None


def token_key(db: Optional[str] = None) -> str:
    """The localStorage key web/src/lib/stdb.ts reads the SpacetimeDB token from."""
    return f"tb_token_{db or os.environ.get('NEXT_PUBLIC_SPACETIMEDB_DB') or os.environ.get('SPACETIMEDB_DB', 'tech-bazaar')}"


def issue_pair_code_via_cli(buyer_id: str, code: str) -> None:
    """The owner's reissue call through the local spacetime CLI (market/scripts/issue_pair_code.py). Raises RuntimeError."""
    import sys
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    import issue_pair_code
    issue_pair_code.issue(buyer_id, code)


def pair_screen(sql: Callable[[str], list], market: Callable[[str], Any], token_file: Path, buyer_id: str = DEMO_BUYER,
                issue: Optional[Callable[[str, str], None]] = None, rotate: bool = False) -> str:
    """Pair the rehearsal's own screen identity with the buyer once and return its token. #449 RT-2: the market keeps only a
    hash of a pairing code, so there is nothing to read back. This makes its own code with `secrets` (stdb.new_pair_code),
    the owner issues it with reissue_pair_code (`issue(buyer_id, code)`; the local spacetime CLI by default), then the screen
    pairs with it. That rotates the buyer's code (screens already paired keep their role), so it happens only when needed:
    when the saved token's identity still holds the buyer role for `buyer_id`, that token is returned and no code is issued
    (a rehearsal run again does not rotate the code); `rotate=True` forces a new code. `sql` is the owner's read-only SQL
    (the role table), `market(token_file)` makes a market client for that identity (market/scripts/stdb.Market).
    Raises RuntimeError with a reason that never contains the code or the token."""
    if not rotate:
        try:
            saved = json.loads(Path(token_file).read_text())
            if has_buyer_role(sql("SELECT * FROM role"), str(saved["identity"]), buyer_id):
                return saved["token"]
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            pass                     # no usable saved screen: pair it below
    import sys
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import new_pair_code
    code = new_pair_code()
    try:
        (issue or issue_pair_code_via_cli)(buyer_id, code)
    except RuntimeError as e:
        raise RuntimeError(f"pairing code was not issued: {str(e).replace(code, '[code]')[:160]}") from None
    Path(token_file).parent.mkdir(parents=True, exist_ok=True)
    client = market(str(token_file))
    try:
        client.call("pair_buyer_screen", buyer_id=buyer_id, code=code)
    except RuntimeError as e:
        msg = str(e).replace(code, "[code]")
        raise RuntimeError(f"pair_buyer_screen refused: {msg[:160]}") from None
    saved = json.loads(Path(token_file).read_text())
    # A wrong code is not an error over HTTP (the reducer returns {paired: false}), so the role row is the proof.
    if not has_buyer_role(sql("SELECT * FROM role"), saved["identity"], buyer_id):
        raise RuntimeError("pairing did not take: the screen identity has no buyer role (wrong or locked code?)")
    return saved["token"]


def has_buyer_role(rows: list, identity: str, buyer_id: str) -> bool:
    """True when the role rows (identity, role, subject_id) hold role buyer for `buyer_id` on this identity."""
    want = identity.lower().removeprefix("0x")
    for r in rows:
        cells = [str(c).strip().strip('"') for c in r]
        if len(cells) >= 3 and cells[0].lower().removeprefix("0x") == want and cells[1] == "buyer" and cells[2] == buyer_id:
            return True
    return False


class _WebSocket:
    """Just enough RFC 6455 for the DevTools protocol on localhost: text frames, client masking, no extensions."""

    def __init__(self, url: str, timeout: float = 15):
        assert url.startswith("ws://")
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("websocket handshake refused")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        head = bytes([0x81])
        n = len(data)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        message = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("websocket closed by the browser")
            if opcode in (0x9, 0xA):          # ping or pong: not part of a message
                continue
            message += payload
            if b0 & 0x80:
                return message.decode()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class PairedBrowser:
    """One headless Chrome with the paired screen token in localStorage for the web origin. `shot(url, path)` has the
    same signature and (ok, error) result as rehearse.chrome_shot."""

    def __init__(self, chrome: str, origin: str, token: str, *, settle: float = 4.0, db: Optional[str] = None):
        self.settle, self._id, self.ws, self.proc = settle, 0, None, None
        self.key, self.token = token_key(db), token
        self.profile = tempfile.mkdtemp(prefix="rehearse-chrome-")
        try:
            root = ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []   # Chrome refuses root without it
            self.proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                          *root, "--window-size=1440,900", "--remote-debugging-port=0",
                                          f"--user-data-dir={self.profile}", "about:blank"],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            port = self._devtools_port()
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10))
            ws = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
            self.ws = _WebSocket(ws)
            self.call("Page.enable")
            # Before ANY page script on every load: the web app reads this token when it connects, so its own
            # onConnect cannot race us with a fresh anonymous token (it saves back the token it connected with).
            self.call("Page.addScriptToEvaluateOnNewDocument", {"source": f"try {{ localStorage.setItem("
                      f"{json.dumps(self.key)}, {json.dumps(token)}) }} catch (e) {{}}"})
        except Exception:
            self.close()
            raise

    def _devtools_port(self, wait: float = 15) -> int:
        f = Path(self.profile) / "DevToolsActivePort"
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if f.exists() and f.read_text().strip():
                return int(f.read_text().split()[0])
            if self.proc.poll() is not None:
                raise RuntimeError(f"chrome exited {self.proc.returncode}")
            time.sleep(0.1)
        raise RuntimeError("chrome did not open its DevTools port")

    def call(self, method: str, params: Optional[dict] = None) -> dict:
        self._id += 1
        mine = self._id
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mine:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message', 'error')}")
                result = msg.get("result", {})
                if "exceptionDetails" in result:          # Runtime.evaluate reports a thrown script this way
                    raise RuntimeError(f"{method}: the page script threw")
                return result

    def _goto(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        end = time.monotonic() + 15
        while time.monotonic() < end:
            state = self.call("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            if state.get("result", {}).get("value") == "complete":
                return
            time.sleep(0.1)
        raise RuntimeError("page did not finish loading in 15 s")

    def stored_token(self) -> Optional[str]:
        return self.call("Runtime.evaluate", {"expression": f"localStorage.getItem({json.dumps(self.key)})",
                                              "returnByValue": True}).get("result", {}).get("value")

    def shot(self, url: str, path: str) -> tuple:
        try:
            self._goto(url)
            time.sleep(self.settle)               # the page connects to the market and renders its rows
            if self.stored_token() != self.token:
                return False, "the page replaced the paired token, so this shot would show the pair gate"
            data = self.call("Page.captureScreenshot", {"format": "png"})["data"]
            Path(path).write_bytes(base64.b64decode(data))
            return True, ""
        except Exception as e:  # a failed shot is a note in the report, never a crash and never a fake pass
            return False, f"paired screenshot failed ({type(e).__name__})"

    def close(self) -> None:
        if self.ws is not None:
            self.ws.close()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


def stdb_market(token_file: str):
    """market/scripts/stdb.Market for one identity (the market's own HTTP bridge)."""
    import sys
    sys.path.insert(0, str(ROOT / "market" / "scripts"))
    from stdb import Market
    return Market(token_file=token_file)
