from sim.wind_tunnel import HELD_OUT, make_builders, run


def test_builders_are_seeded_and_include_held_out_archetypes():
    a, b = make_builders(10, seed=1), make_builders(10, seed=1)
    assert a == b and len(a) == 10
    assert {x["archetype"] for x in a} & set(HELD_OUT)
    assert all(x["case"]["max_gpu_length_mm"] and x["psu"]["wattage"] for x in a)



def test_small_run_is_labelled_sim_and_reports_both_arms():
    out = run(builders=6, seeds=1)
    assert out["origin"] == "SIM" and out["seeds"] == [0]
    assert "quotable" in out["learning"] and out["learning"]["held_out_archetypes"] == list(HELD_OUT)
    assert out["attack"]["held_out"]["attacks"] == 20 and out["attack"]["held_out"]["controls"] == 10


# #34: quote gate on distinct held-out archetypes, not on rounds
from sim.wind_tunnel import quote_gate  # noqa: E402


def test_one_winning_archetype_is_not_quotable_however_many_rounds():
    per_arch = {"open_box_ok": {"n": 45, "learner": 0.0, "control_median": 0.0},
                "small_case": {"n": 45, "learner": 1.0, "control_median": 0.0}}
    ok, winning = quote_gate(per_arch, "control_median")
    assert not ok and winning == ["small_case"]


def test_two_winning_archetypes_are_quotable():
    per_arch = {"open_box_ok": {"n": 9, "learner": 0.6, "control_median": 0.2},
                "small_case": {"n": 9, "learner": 0.7, "control_median": 0.3}}
    assert quote_gate(per_arch, "control_median") == (True, ["open_box_ok", "small_case"])


def test_results_report_both_controls_and_per_archetype_rows():
    from sim.wind_tunnel import CONTROL_MEDIAN, markdown, run
    out = run(builders=6, seeds=2)
    md = markdown(out)
    assert CONTROL_MEDIAN in md and "fair-price-pc" in md and "untrained" in md
    assert "small_case" in md and "open_box_ok" in md
    assert "demo.learning.update_strategy" in md
