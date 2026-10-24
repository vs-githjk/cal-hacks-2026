"""SSRF-guarded fetch for caller-supplied listing URLs (Lane C). Used by the claim check, its Apify Actor and Shield."""
from __future__ import annotations

import io
import ipaddress
import socket
import time
from urllib.parse import urlparse

MAX_PAGE_BYTES = 2 * 1024 * 1024  # a listing page larger than 2 MB is refused (could not verify)
MAX_REDIRECTS = 3
DEADLINE_S = 30.0  # the whole fetch (every hop and the body), so a server that drips bytes cannot hold a run open
UA = "TechBazaar-claim-check/0.1 (hackathon research)"
CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _allowed(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or (ip.version == 4 and ip in CGNAT))


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}") from e


class _Deadline:
    """The time one hop may still take; the body reader moves `end` to the whole fetch's deadline."""
    def __init__(self, end: float, clock=time.monotonic):
        self.end, self.clock = end, clock

    def left(self) -> float:
        left = self.end - self.clock()
        if left <= 0:
            raise _past_deadline()
        return left


class _DeadlineIO(io.RawIOBase):
    """The response stream: before EVERY socket read the timeout is set to the time left, so a server that drips the
    status line or headers one byte a second cannot outlast the deadline (a plain socket timeout resets on each byte)."""
    def __init__(self, sock, deadline: _Deadline):
        super().__init__()
        self.sock, self.deadline = sock, deadline

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        self.sock.settimeout(self.deadline.left())
        try:
            return self.sock.recv_into(b)
        except socket.timeout as e:
            raise _past_deadline() from e


class _DeadlineSock:
    """What http.client.HTTPResponse is given in place of the socket: its makefile() is the deadline-bound stream."""
    def __init__(self, sock, deadline: _Deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode="rb", *a, **k):
        return io.BufferedReader(_DeadlineIO(self.sock, self.deadline))


def _request(scheme: str, host: str, port: int, path: str, ip: str, timeout: float, clock=time.monotonic):
    """One GET to the already-checked IP (no second DNS lookup), with Host and TLS SNI set to the name. `timeout` bounds the
    whole hop up to the end of the headers (connect, TLS handshake, request, status line and headers), not each read."""
    import http.client
    import ssl
    import threading
    deadline = _Deadline(clock() + timeout, clock)
    sock = socket.create_connection((ip, port), timeout=deadline.left())
    if scheme == "https":
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        sock.settimeout(deadline.left())
        # the handshake reads inside the ssl module, out of _DeadlineIO's reach: a watchdog cuts it off at the deadline
        dog = threading.Timer(deadline.left(), lambda: _shutdown(sock))
        dog.daemon = True
        dog.start()
        try:
            sock = ctx.wrap_socket(sock, server_hostname=host)
        finally:
            dog.cancel()
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.sock = sock
    conn.response_class = lambda s, *a, **k: http.client.HTTPResponse(_DeadlineSock(s, deadline), *a, **k)
    sock.settimeout(deadline.left())
    conn.request("GET", path, headers={"Host": host, "User-Agent": UA})
    r = conn.getresponse()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, _BodyReader(r, sock, deadline)


def _shutdown(sock) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _past_deadline() -> ValueError:
    return ValueError("page fetch passed the overall deadline")


def _read_body(resp, sock, n: int, end: float, clock=time.monotonic) -> bytes:
    """Up to n bytes, a chunk at a time, stopping with ValueError once clock() passes end (a socket timeout alone resets
    on every byte, so one byte every few seconds would never trip it)."""
    chunks, got = [], 0
    while got < n:
        left = end - clock()
        if left <= 0:
            raise _past_deadline()
        if sock is not None:
            sock.settimeout(left)
        chunk = resp.read1(min(65536, n - got))
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    if clock() > end:
        raise _past_deadline()
    return b"".join(chunks)


class _BodyReader:
    """What _request returns as its reader: guarded_get reads it under the overall deadline. Called plainly, read(n)."""
    def __init__(self, resp, sock, deadline: _Deadline | None = None):
        self.resp, self.sock, self.deadline = resp, sock, deadline

    def __call__(self, n: int, end: float | None = None, clock=time.monotonic) -> bytes:
        end = clock() + DEADLINE_S if end is None else end
        if self.deadline is not None:  # the body may use what is left of the whole fetch, not only this hop's time
            self.deadline.end, self.deadline.clock = end, clock
        return _read_body(self.resp, self.sock, n, end, clock)


def guarded_get(url: str, *, resolve=_resolve, request=_request, max_bytes: int = MAX_PAGE_BYTES,
                max_redirects: int = MAX_REDIRECTS, timeout: float = 15.0, deadline: float = DEADLINE_S,
                clock=time.monotonic) -> bytes:
    """Fetch a caller-supplied URL safely: http(s) only; every hop's host is resolved and EVERY address must be public
    (no localhost, private, link-local or cloud metadata, CGNAT, reserved, multicast); we connect to the checked IP
    itself, so DNS cannot change between check and connect; redirects are followed by hand and re-checked; the body
    is capped at max_bytes; the whole fetch must finish within `deadline` seconds. Any refusal raises ValueError, which the
    claim check reports as could not verify."""
    from urllib.parse import urljoin
    end = clock() + deadline
    for _ in range(max_redirects + 1):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise ValueError("only http and https URLs with a host are fetched")
        ips = resolve(p.hostname)
        if not ips or not all(_allowed(ip) for ip in ips):
            raise ValueError("address not allowed")
        port = p.port or (443 if p.scheme == "https" else 80)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        left = end - clock()
        if left <= 0:
            raise _past_deadline()
        status, headers, read = request(p.scheme, p.hostname, port, path, ips[0], min(timeout, left))
        if status in (301, 302, 303, 307, 308):
            if not headers.get("location"):
                raise ValueError("redirect without a location")
            url = urljoin(url, headers["location"])
            continue
        if status != 200:
            raise ValueError(f"http {status}")
        body = read(max_bytes + 1, end, clock) if isinstance(read, _BodyReader) else read(max_bytes + 1)
        if clock() > end:
            raise _past_deadline()
        if len(body) > max_bytes:
            raise ValueError(f"page too large (over {max_bytes} bytes)")
        return body
    raise ValueError("too many redirects")

