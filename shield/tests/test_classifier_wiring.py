"""Task 2: SHIELD_MODEL, and run_corpus --classifier that goes live only when explicitly enabled. No network here."""
import json
import os
import urllib.request

import pytest

from shield import classifier as clf_mod
from shield.classifier import DEFAULT_MODEL, ClaudeClassifier, default_classifier
from shield.corpus import run_corpus


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network call attempted in a test")
    monkeypatch.setattr(urllib.request, "urlopen", boom)


def test_default_model_is_haiku_and_shield_model_overrides(monkeypatch):
    assert DEFAULT_MODEL == "claude-haiku-4-5"
    monkeypatch.delenv("SHIELD_MODEL", raising=False)
    assert ClaudeClassifier("k")._model == "claude-haiku-4-5"
    monkeypatch.setenv("SHIELD_MODEL", "claude-test-model")
    assert ClaudeClassifier("k")._model == "claude-test-model"
    assert ClaudeClassifier("k", model="explicit")._model == "explicit"  # an explicit argument beats the env
    monkeypatch.setenv("SHIELD_MODEL", "")
    assert ClaudeClassifier("k")._model == "claude-haiku-4-5"  # blank means default


def test_model_id_goes_into_the_request_body(monkeypatch):
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"content": [{"text": "SAFE"}]}).encode()

    def fake(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return R()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setenv("SHIELD_MODEL", "claude-test-model")
    assert ClaudeClassifier("k").classify("hi", {}) == "SAFE"
    assert seen["body"]["model"] == "claude-test-model"


def test_load_dotenv_reads_only_known_names_and_never_overrides(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nANTHROPIC_API_KEY=\"sk-test-from-file\"\nSHIELD_CLASSIFIER=1\nOTHER_SECRET=zzz\nSHIELD_MODEL=m1\n", encoding="utf-8")
    env = {"SHIELD_MODEL": "already-set"}
    run_corpus.load_dotenv(str(f), env)
    assert env["ANTHROPIC_API_KEY"] == "sk-test-from-file" and env["SHIELD_CLASSIFIER"] == "1"
    assert env["SHIELD_MODEL"] == "already-set" and "OTHER_SECRET" not in env
    run_corpus.load_dotenv(str(tmp_path / "missing.env"), env)  # a missing file is fine


def test_classifier_flag_without_both_switches_makes_no_call_and_prints_why(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)
    rc = run_corpus.main(["--classifier"], env_file=str(tmp_path / "none.env"))
    out = capsys.readouterr().out
    assert rc == 0 and "not enabled" in out and "ANTHROPIC_API_KEY" in out and "SHIELD_CLASSIFIER=1" in out


def test_key_alone_or_flag_alone_is_not_enough(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret-value")
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)
    assert run_corpus.main(["--classifier"], env_file=str(tmp_path / "none.env")) == 0
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("SHIELD_CLASSIFIER", "1")
    assert run_corpus.main(["--classifier"], env_file=str(tmp_path / "none.env")) == 0
    assert "sk-test-secret-value" not in capsys.readouterr().out


def test_enabled_run_uses_the_classifier_reports_unavailable_separately_and_never_prints_the_key(monkeypatch, capsys, tmp_path):
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=sk-test-secret-value\nSHIELD_CLASSIFIER=1\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)
    calls = []

    class Fake:
        def classify(self, message, ctx):
            calls.append(message)
            return "SUSPICIOUS" if "bit.ly" in message else "SAFE"
    monkeypatch.setattr(run_corpus, "make_classifier", lambda env: Fake())
    rc = run_corpus.main(["--classifier"], env_file=str(f))
    out = capsys.readouterr().out
    assert "sk-test-secret-value" not in out
    assert calls, "the classifier should have been consulted on messages the rules allowed"
    assert "classifier suspicious" in out and "classifier unavailable" in out and "held-out" in out
    assert rc == 0
    assert "ANTHROPIC_API_KEY" not in os.environ  # the file is read into a copy, never into this process


def test_classifier_that_errors_is_counted_as_unavailable_not_as_a_catch(monkeypatch, capsys, tmp_path):
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=k\nSHIELD_CLASSIFIER=1\n", encoding="utf-8")

    class Broken:
        def classify(self, message, ctx):
            raise OSError("model id rejected")
    monkeypatch.setattr(run_corpus, "make_classifier", lambda env: Broken())
    run_corpus.main(["--classifier"], env_file=str(f))
    out = capsys.readouterr().out
    assert "WARNING" in out and "unavailable" in out  # a wrong model id must not read as a good result
