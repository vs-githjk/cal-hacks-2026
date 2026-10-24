from sim.wind_tunnel import HELD_OUT, make_builders, run, summarize_lift


def test_builders_are_seeded_and_include_held_out_archetypes():
    a, b = make_builders(10, seed=1), make_builders(10, seed=1)
    assert a == b and len(a) == 10
    assert {x["archetype"] for x in a} & set(HELD_OUT)
    assert all(x["case"]["max_gpu_length_mm"] and x["psu"]["wattage"] for x in a)


def test_lift_is_learner_minus_control_and_can_be_negative():
    s = summarize_lift([{"learner": 0.5, "control": 0.5, "untrained": 0.5}, {"learner": 0.0, "control": 0.5, "untrained": 0.0}])
    assert s["lift_mean"] == -0.25 and s["lift_range"] == (-0.5, 0.0)


def test_small_run_is_labelled_sim_and_reports_both_arms():
    out = run(builders=6, seeds=1)
    assert out["origin"] == "SIM" and out["seeds"] == [0]
    assert "lift_mean" in out["learning"] and out["learning"]["held_out_archetypes"] == list(HELD_OUT)
    assert out["attack"]["held_out"]["attacks"] == 20 and out["attack"]["held_out"]["controls"] == 10
