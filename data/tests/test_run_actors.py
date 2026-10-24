import json

from data.mirror import run_actors


def test_a_skipped_record_never_replaces_a_real_run(tmp_path, monkeypatch):  # #129
    real = {"store": "bestbuy", "run_id": "RUN1", "snapshot_id": "bestbuy-x", "status": "SUCCEEDED", "items": 3}
    skipped = {"store": "bestbuy", "status": "SKIPPED", "error": "no actor for bestbuy"}
    other = {"store": "bestbuy", "family": "b", "run_id": "RUNB", "status": "SUCCEEDED"}
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "runs.json").write_text(json.dumps([real, skipped, other]))
    monkeypatch.setattr(run_actors, "HERE", tmp_path)
    calls = []

    def call(method, path, body=None, timeout=330):
        calls.append(path)
        if path.startswith("/actor-runs/"):
            return {"data": {"defaultDatasetId": "D", "finishedAt": "2026-10-24T05:00:00Z", "usageTotalUsd": 0.01}}
        return [{"title": "RTX 5070 Ti", "url": "https://x.test/1", "price": "$1,000"}]

    monkeypatch.setattr(run_actors, "call", call)
    out = run_actors.renormalize()
    assert [r["run_id"] for r in out] == ["RUN1"] and calls[0] == "/actor-runs/RUN1"
    saved = json.loads((tmp_path / "runs.json").read_text())
    assert len(saved) == 3 and saved[1] == skipped and saved[2] == other and saved[0]["cost_usd"] == 0.01


def test_cli_line_shows_the_skip_reason():
    assert "no second-family actor for amazon" in run_actors.describe(
        {"store": "amazon", "status": "SKIPPED", "error": "no second-family actor for amazon"})
    assert "SUCCEEDED" in run_actors.describe({"store": "bestbuy", "status": "SUCCEEDED", "items": 3})
