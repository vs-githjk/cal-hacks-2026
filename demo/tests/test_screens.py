"""#184: rehearsal screenshots pair the buyer screen first. Fakes for the market; a real headless Chromium (when one is
installed) for the DevTools client."""
import http.server
import json
import threading

import pytest

from demo import rehearse, screens

CODE = "K7Q2M-9XW4P"


class FakeMarket:
    def __init__(self, token_file, fail=None):
        self.token_file, self.fail, self.calls = token_file, fail, []
        open(token_file, "w").write(json.dumps({"token": "tok-screen-1", "identity": "abc"}))

    def call(self, reducer, **args):
        self.calls.append((reducer, args))
        if self.fail:
            raise RuntimeError(self.fail)


def test_pair_screen_reads_the_code_once_pairs_once_and_returns_the_token(tmp_path):
    made, queries = [], []

    def sql(q):
        queries.append(q)
        return [[f'"{CODE}"']]

    def market(path):
        made.append(FakeMarket(path))
        return made[-1]
    token = screens.pair_screen(sql, market, tmp_path / "t.json")
    assert token == "tok-screen-1" and queries == ["SELECT code FROM pair_code WHERE buyer_id = 'vidyut'"]
    assert made[0].calls == [("pair_buyer_screen", {"buyer_id": "vidyut", "code": CODE})]     # entered exactly once


def test_a_refused_pairing_never_echoes_the_code(tmp_path):
    with pytest.raises(RuntimeError) as e:
        screens.pair_screen(lambda q: [[CODE]], lambda p: FakeMarket(p, fail=f"code {CODE} did not match"), tmp_path / "t.json")
    assert CODE not in str(e.value) and "[code]" in str(e.value)


def test_no_code_issued_is_a_clear_refusal(tmp_path):
    with pytest.raises(RuntimeError, match="no pairing code"):
        screens.pair_screen(lambda q: [], lambda p: FakeMarket(p), tmp_path / "t.json")


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
    shoot, browser, note = rehearse.paired_shooter(lambda q: [[CODE]], market=lambda p: FakeMarket(p), browser_cls=Browser,
                                                   chrome="/bin/true")
    assert seen == {"chrome": "/bin/true", "origin": f"http://localhost:{rehearse.WEB_PORT}/", "token": "tok-screen-1"}
    assert shoot == browser.shot and "paired once" in note and "tok-screen-1" not in note


def test_the_token_key_matches_the_web_app():
    from pathlib import Path
    src = (Path(screens.ROOT) / "web" / "src" / "lib" / "stdb.ts").read_text()
    assert "tb_token_${STDB_DB}" in src and screens.token_key("tech-bazaar") == "tb_token_tech-bazaar"


@pytest.mark.skipif(screens.find_chrome() is None, reason="no Chrome or Chromium installed")
def test_a_real_headless_chrome_gets_the_token_and_takes_the_shot(tmp_path):
    page = b"<html><body><h1 id=t></h1><script>document.getElementById('t').textContent = " \
           b"localStorage.getItem('tb_token_tech-bazaar') || 'unpaired'</script></body></html>"

    class Page(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{srv.server_port}/"
    b = screens.PairedBrowser(screens.find_chrome(), origin, "tok-real-1", settle=0.5, db="tech-bazaar")
    try:
        ok, err = b.shot(origin + "buyer", str(tmp_path / "buyer.png"))
        shown = b.call("Runtime.evaluate", {"expression": "document.getElementById('t').textContent", "returnByValue": True})
    finally:
        b.close()
        srv.shutdown()
    assert ok and err == "" and (tmp_path / "buyer.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert shown["result"]["value"] == "tok-real-1"            # the page read the paired token from localStorage
