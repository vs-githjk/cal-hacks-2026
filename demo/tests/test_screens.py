"""#184: rehearsal screenshots pair the buyer screen first. Fakes for the market; a real headless Chromium (when one is
installed) for the DevTools client."""
import http.server
import json
import re
import threading

import pytest

from demo import rehearse, screens

ROLE_ROWS = [['0xabc', '"buyer"', '"vidyut"']]
CODE_SHAPE = r"[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}"


def owner_sql(role_rows=None):
    """The owner's read-only SQL: only the role table now. #449 RT-2: pair_code holds a hash, so there is no code to read."""
    def sql(q):
        assert "pair_code" not in q, "the code is made here and issued by the owner, never read back"
        return ROLE_ROWS if role_rows is None else role_rows
    return sql


class Issuer:
    """The owner's reissue call, faked: records (buyer_id, code), optionally fails with a message."""
    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def __call__(self, buyer_id, code):
        self.calls.append((buyer_id, code))
        if self.fail:
            raise RuntimeError(self.fail.replace("{code}", code))


class FakeMarket:
    def __init__(self, token_file, fail=None):
        self.token_file, self.fail, self.calls = token_file, fail, []
        open(token_file, "w").write(json.dumps({"token": "tok-screen-1", "identity": "abc"}))

    def call(self, reducer, **args):
        self.calls.append((reducer, args))
        if self.fail:
            raise RuntimeError(self.fail)


def test_pair_screen_issues_its_own_code_once_pairs_once_and_returns_the_token(tmp_path):
    made, queries, issue = [], [], Issuer()
    inner = owner_sql()

    def sql(q):
        queries.append(q)
        return inner(q)

    def market(path):
        made.append(FakeMarket(path))
        return made[-1]
    token = screens.pair_screen(sql, market, tmp_path / "sub" / "t.json", issue=issue)        # the .tokens folder is created
    assert token == "tok-screen-1"
    assert queries == ["SELECT * FROM role"]                                  # the private pair_code table is never read
    assert len(issue.calls) == 1 and issue.calls[0][0] == "vidyut" and re.fullmatch(CODE_SHAPE, issue.calls[0][1])
    assert made[0].calls == [("pair_buyer_screen", {"buyer_id": "vidyut", "code": issue.calls[0][1]})]     # the issued code, entered exactly once


def test_each_pairing_makes_a_fresh_code(tmp_path):
    codes = set()
    for _ in range(5):
        issue = Issuer()
        screens.pair_screen(owner_sql(), lambda p: FakeMarket(p), tmp_path / "t.json", issue=issue)
        codes.add(issue.calls[0][1])
    assert len(codes) == 5


def test_a_refused_pairing_never_echoes_the_code(tmp_path):
    class Echo(FakeMarket):
        def call(self, reducer, **args):
            raise RuntimeError(f"code {args['code']} did not match")
    issue = Issuer()
    with pytest.raises(RuntimeError) as e:
        screens.pair_screen(owner_sql(), lambda p: Echo(p), tmp_path / "t.json", issue=issue)
    code = issue.calls[-1][1]
    assert code not in str(e.value) and "[code]" in str(e.value)


def test_a_failed_reissue_never_echoes_the_code_and_pairs_nothing(tmp_path):
    made = []

    def market(path):
        made.append(path)
        return FakeMarket(path)
    issue = Issuer(fail="spacetime call exited 1: bad args {code}")
    with pytest.raises(RuntimeError, match="pairing code was not issued") as e:
        screens.pair_screen(owner_sql(), market, tmp_path / "t.json", issue=issue)
    assert issue.calls[0][1] not in str(e.value) and "[code]" in str(e.value)
    assert made == []                                                         # no screen identity was made or paired


@pytest.mark.parametrize("rows", [[], [['0xabc', '"seller"', '"vidyut"']], [['0xother', '"buyer"', '"vidyut"']],
                                  [['0xabc', '"buyer"', '"buyer-2"']]])
def test_a_pairing_that_did_not_take_is_never_reported_as_paired(tmp_path, rows):
    """A wrong code is not an HTTP error (the reducer returns paired false), so the role row is checked."""
    with pytest.raises(RuntimeError, match="did not take"):
        screens.pair_screen(owner_sql(role_rows=rows), lambda p: FakeMarket(p), tmp_path / "t.json", issue=Issuer())


def test_paired_shooter_falls_back_to_plain_shots_and_says_buyer_is_not_paired():
    def down(q):
        raise RuntimeError("spacetime sql exited 1")
    shoot, browser, note = rehearse.paired_shooter(down)
    assert shoot is rehearse.chrome_shot and browser is None and "NOT paired" in note


def test_paired_shooter_uses_the_paired_browser_when_pairing_works(tmp_path, monkeypatch):
    seen = {}

    class Browser:
        def __init__(self, chrome, origin, token):
            seen.update(chrome=chrome, origin=origin, token=token)

        def shot(self, url, path):
            return True, ""
    monkeypatch.setattr(rehearse, "ROOT", tmp_path)
    (tmp_path / ".tokens").mkdir()
    shoot, browser, note = rehearse.paired_shooter(owner_sql(), market=lambda p: FakeMarket(p), browser_cls=Browser,
                                                   chrome="/bin/true", issue=Issuer())
    assert seen == {"chrome": "/bin/true", "origin": f"http://localhost:{rehearse.WEB_PORT}/", "token": "tok-screen-1"}
    assert shoot == browser.shot and "paired once" in note and "tok-screen-1" not in note


def test_the_token_key_matches_the_web_app():
    from pathlib import Path
    src = (Path(screens.ROOT) / "web" / "src" / "lib" / "stdb.ts").read_text()
    assert "tb_token_${STDB_DB}" in src and screens.token_key("tech-bazaar") == "tb_token_tech-bazaar"


# The web app's own behaviour (web/src/lib/stdb.ts): connect with the stored token, then save the token the server returns.
# A stored token comes back unchanged; with none the server issues a fresh anonymous one ("ANON" here), 300 ms later.
LIKE_THE_APP = b"<html><body><h1 id=t></h1><script>const k = 'tb_token_tech-bazaar'; const had = localStorage.getItem(k);" \
               b"setTimeout(() => { localStorage.setItem(k, had || 'ANON');" \
               b"document.getElementById('t').textContent = localStorage.getItem(k) }, 300)</script></body></html>"
HOSTILE = b"<html><body><script>localStorage.setItem('tb_token_tech-bazaar', 'ANON')</script></body></html>"


def serve(pages):
    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(pages.get(self.path, pages["/"]))

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/"


def browser_or_skip(origin, token):
    try:
        return screens.PairedBrowser(screens.find_chrome(), origin, token, settle=0.8, db="tech-bazaar")
    except RuntimeError as e:          # e.g. a CI runner whose sandbox will not start Chrome: not this code's failure
        pytest.skip(f"Chrome would not start here: {e}")


@pytest.mark.skipif(screens.find_chrome() is None, reason="no Chrome or Chromium installed")
def test_a_real_headless_chrome_keeps_the_paired_token_through_the_apps_own_connect(tmp_path):
    srv, origin = serve({"/": LIKE_THE_APP})
    b = browser_or_skip(origin, "tok-real-1")
    try:
        ok, err = b.shot(origin + "buyer", str(tmp_path / "buyer.png"))
        shown = b.call("Runtime.evaluate", {"expression": "document.getElementById('t').textContent", "returnByValue": True})
    finally:
        b.close()
        srv.shutdown()
    assert ok and err == "" and (tmp_path / "buyer.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert shown["result"]["value"] == "tok-real-1"            # the app connected with the paired token and kept it


@pytest.mark.skipif(screens.find_chrome() is None, reason="no Chrome or Chromium installed")
def test_a_page_that_replaces_the_token_gives_no_shot_and_says_why(tmp_path):
    srv, origin = serve({"/": HOSTILE})
    b = browser_or_skip(origin, "tok-real-2")
    try:
        ok, err = b.shot(origin + "buyer", str(tmp_path / "buyer.png"))
    finally:
        b.close()
        srv.shutdown()
    assert not ok and "replaced the paired token" in err and not (tmp_path / "buyer.png").exists()


@pytest.mark.skipif(screens.find_chrome() is None, reason="no Chrome or Chromium installed")
def test_a_script_that_throws_raises_instead_of_passing_silently():
    srv, origin = serve({"/": LIKE_THE_APP})
    b = browser_or_skip(origin, "tok-real-3")
    try:
        with pytest.raises(RuntimeError, match="threw"):
            b.call("Runtime.evaluate", {"expression": "(() => { throw new Error('x') })()"})
    finally:
        b.close()
        srv.shutdown()
