"""#449 RT-26: the buyer's local REST chat (/chat) answers loopback callers only. uagents' REST handler never sees the
request (no client host, no headers), so the gate sits in front of the agent's own ASGI server. No network."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rest_gate  # noqa: E402


def scope(client=("127.0.0.1", 50000), path="/chat", method="POST", headers=()):
    return {"type": "http", "method": method, "path": path, "client": client,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers]}


@pytest.mark.parametrize("client", [("127.0.0.1", 1), ("127.8.9.10", 1), ("::1", 1), ("::ffff:127.0.0.1", 1)])
def test_loopback_callers_are_allowed(client):
    assert rest_gate.permitted(scope(client), {}) is True


@pytest.mark.parametrize("client", [("192.168.1.20", 1), ("10.0.0.5", 1), ("203.0.113.9", 1), ("::ffff:203.0.113.9", 1),
                                    ("2001:db8::1", 1), ("localhost.evil.test", 1), ("", 1), (None, 1), None, ("not-an-ip",)])
def test_everyone_else_is_refused(client):
    assert rest_gate.permitted(scope(client), {}) is False


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Host", "X-Forwarded-Proto"])
def test_a_forwarding_header_is_refused_because_uvicorn_trusts_it_and_rewrites_the_client(header):
    """uagents runs uvicorn with forwarded_allow_ips="*": a remote caller can send X-Forwarded-For: 127.0.0.1 and
    arrive as 'loopback'. Any proxy header means the client host is not to be believed."""
    assert rest_gate.permitted(scope(headers=[(header, "127.0.0.1")]), {}) is False


def test_a_browser_page_is_refused_even_on_this_machine():
    """uagents answers CORS preflight with Access-Control-Allow-Origin *, so a web page the owner has open could
    POST to localhost. Browsers always send Origin; the web_chat.py proxy and curl do not."""
    assert rest_gate.permitted(scope(headers=[("Origin", "https://evil.example.test")]), {}) is False
    assert rest_gate.permitted(scope(method="OPTIONS", headers=[("Origin", "http://localhost:3000"),
                                                                 ("Access-Control-Request-Method", "POST")]), {}) is False


def test_with_a_token_set_the_bearer_must_match_and_loopback_is_still_required():
    env = {"BUYER_REST_TOKEN": "s3cret-token-value"}
    ok = [("Authorization", "Bearer s3cret-token-value")]
    assert rest_gate.permitted(scope(headers=ok), env) is True
    assert rest_gate.permitted(scope(), env) is False                                             # no header
    assert rest_gate.permitted(scope(headers=[("Authorization", "Bearer s3cret-token-valuX")]), env) is False
    assert rest_gate.permitted(scope(headers=[("Authorization", "Bearer s3cret-token-value ")]), env) is True   # trailing space
    assert rest_gate.permitted(scope(headers=[("Authorization", "s3cret-token-value")]), env) is False      # no scheme
    assert rest_gate.permitted(scope(headers=[("Authorization", "Basic s3cret-token-value")]), env) is False
    assert rest_gate.permitted(scope(headers=[("Authorization", "Bearer é")]), env) is False       # non-ASCII, no crash
    assert rest_gate.permitted(scope(client=("203.0.113.9", 1), headers=ok), env) is False       # right token, wrong host


def test_the_token_is_compared_in_constant_time():
    import inspect
    assert "compare_digest" in inspect.getsource(rest_gate)


def test_an_empty_or_blank_token_is_not_a_token():
    assert rest_gate.permitted(scope(), {"BUYER_REST_TOKEN": ""}) is True
    assert rest_gate.permitted(scope(), {"BUYER_REST_TOKEN": "   "}) is True


# ---- install(): the real uagents ASGIServer, driven with raw ASGI messages ------------------------------------------
def make_agent():
    from uagents import Model
    from uagents.asgi import ASGIServer

    class In(Model):
        text: str

    class Out(Model):
        replies: list[str]
    loop = asyncio.new_event_loop()
    server = ASGIServer(8001, loop, {})
    server.add_rest_endpoint("agent1qtest", "POST", "/chat", In, Out)
    server.add_rest_endpoint("agent1qtest", "GET", "/chat", None, Out)
    reached = []

    async def fake_handle_rest(headers, handlers, send, receive):
        reached.append(1)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})
    server._handle_rest = fake_handle_rest
    return SimpleNamespace(_server=server), reached, loop


def call(server, sc):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message):
        sent.append(message)
    asyncio.run(server(sc, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


@pytest.fixture
def gated(monkeypatch):
    monkeypatch.delenv("BUYER_REST_TOKEN", raising=False)
    agent, reached, loop = make_agent()
    rest_gate.install(agent)
    yield agent._server, reached
    loop.close()


def test_install_lets_a_loopback_chat_reach_the_handler_and_stops_a_stranger_before_it(gated):
    server, reached = gated
    assert call(server, scope())[0] == 200 and reached == [1]
    assert call(server, scope(method="GET"))[0] == 200 and reached == [1, 1]
    status, body = call(server, scope(client=("203.0.113.9", 4444)))
    assert status == 403 and b"forbidden" in body and reached == [1, 1]            # the handler never ran
    assert call(server, scope(client=("203.0.113.9", 4444), method="GET"))[0] == 403
    assert call(server, scope(headers=[("X-Forwarded-For", "127.0.0.1")], client=("203.0.113.9", 4444)))[0] == 403
    assert call(server, scope(method="OPTIONS", headers=[("Origin", "https://evil.example.test")]))[0] == 403
    assert reached == [1, 1]


def test_install_reads_the_token_per_request(gated, monkeypatch):
    server, reached = gated
    monkeypatch.setenv("BUYER_REST_TOKEN", "tok-1234567890")
    assert call(server, scope())[0] == 403
    assert call(server, scope(headers=[("Authorization", "Bearer tok-1234567890")]))[0] == 200


def test_install_leaves_agent_to_agent_and_other_paths_alone(gated):
    server, reached = gated
    # /submit is how other agents reach us; the gate is for the REST endpoints we registered, not for that
    status, _ = call(server, scope(path="/nope", client=("203.0.113.9", 1)))
    assert status == 404                      # uagents' own answer, not the gate's 403


def test_install_fails_loudly_when_the_server_cannot_be_wrapped():
    with pytest.raises(RuntimeError, match="REST"):
        rest_gate.install(SimpleNamespace())
    with pytest.raises(RuntimeError, match="REST"):
        rest_gate.install(SimpleNamespace(_server=object()))


def test_install_twice_wraps_once(monkeypatch):
    monkeypatch.delenv("BUYER_REST_TOKEN", raising=False)
    agent, reached, loop = make_agent()
    try:
        rest_gate.install(agent)
        cls = type(agent._server)
        rest_gate.install(agent)
        assert type(agent._server) is cls
    finally:
        loop.close()


def test_the_buyer_installs_the_gate_before_it_serves():
    src = (Path(__file__).with_name("buyer_agent.py")).read_text()
    assert src.index("rest_gate.install(agent)") < src.index("agent.run()")


def test_web_chat_sends_the_token_when_one_is_set(monkeypatch):
    import web_chat
    monkeypatch.delenv("BUYER_REST_TOKEN", raising=False)
    assert "Authorization" not in web_chat.buyer_headers()
    monkeypatch.setenv("BUYER_REST_TOKEN", "tok-1234567890")
    assert web_chat.buyer_headers()["Authorization"] == "Bearer tok-1234567890"
    assert web_chat.buyer_headers()["Content-Type"] == "application/json"
