import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_demo


def test_run1_resolves_within_cap_and_says_sim(capsys):
    out = build_demo.run("run 1", {})
    assert out["status"] == "plan_ready"
    assert out["planned_total_cents"] == 51000 <= out["cap_cents"]
    text = capsys.readouterr().out
    assert "SIM" in text and "plan ready" in text


def test_run2_refused_with_length_reason(capsys):
    out = build_demo.run("run 2", {"length_mm": 400})
    assert out["status"] == "blocked"
    assert "fit.gpu_length" in out["blocked_reasons"][0]
    text = capsys.readouterr().out
    assert "SIM refused" in text and "fit.gpu_length" in text


def test_output_has_no_dashes(capsys):
    build_demo.main()
    assert "—" not in capsys.readouterr().out and "–" not in build_demo.__doc__
