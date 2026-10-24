from sim.leak import CONFIGS, DEFAULT_BANDS, COARSE_BANDS, collude, market, probe


def test_market_is_seeded_and_within_one_percent_of_the_real_band():
    assert market(0) == market(0) and market(0) != market(1)
    assert all(abs(v / b - 1) <= 0.0101 for v, b in zip(market(0).values(), (1199.0, 1248.50, 1289.0)))


def test_probe_rounds_are_deterministic_with_fixed_seeds():
    assert [probe(s, DEFAULT_BANDS, 1)["rounds"] for s in range(3)] == [3, 2, 3]
    assert [probe(s, COARSE_BANDS, 1)["rounds"] for s in range(3)] == [6, 6, 6]
    assert [probe(s, DEFAULT_BANDS, 3)["rounds"] for s in range(3)] == [7, 4, 7]
    assert [probe(s, COARSE_BANDS, 3)["rounds"] for s in range(3)] == [16, 16, 16]


def test_each_mitigation_slows_the_probe_on_these_seeds():
    base = [probe(s, DEFAULT_BANDS, 1)["rounds"] for s in range(3)]
    for bands, every in ((COARSE_BANDS, 1), (DEFAULT_BANDS, 3)):
        assert all(m > b for m, b in zip([probe(s, bands, every)["rounds"] for s in range(3)], base))


def test_probe_reports_when_the_cap_is_hit():
    out = probe(0, COARSE_BANDS, 40)
    assert out["reached"] is False and out["rounds"] is None


def test_learners_do_not_raise_the_clearing_price_in_any_config():
    for bands, every in CONFIGS.values():
        for with_controls in (True, False):
            for seed in range(3):
                r = collude(seed, bands, every, with_controls)
                assert r["rose"] is False
                if with_controls:
                    assert r["r1"] <= r["cheapest_control"] and r["r20"] <= r["cheapest_control"]
