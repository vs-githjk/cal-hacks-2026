"""Demo tests are offline: a BRIGHT_DATA_API_KEY in the shell must never turn beat 4's live re-check on."""
import pytest


@pytest.fixture(autouse=True)
def _no_bright_data_key(monkeypatch):
    monkeypatch.delenv("BRIGHT_DATA_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_shield_classifier(monkeypatch):
    """Keyed shells must not turn the live Claude classifier on inside the offline demo tests (module-scoped fixtures
    that need a classifier patch shield.core.default_classifier with a stub instead)."""
    monkeypatch.delenv("SHIELD_CLASSIFIER", raising=False)


@pytest.fixture(autouse=True)
def _crs_sim_labels(monkeypatch, tmp_path_factory):
    """#449 RT-25: no CRS profile file no longer makes a payee a SIM seller, so the demo's two SIM winners (the stage
    run's best-buy and gadget-grove) are labelled SIM the way an operator would, in a private profile file. A test that
    is about CRS sets or removes CRS_TEST_IDENTITIES_PATH itself."""
    import json
    folder = tmp_path_factory.mktemp("crs-sim-labels")   # not the test's own tmp_path: some tests assert it stays empty
    path = folder / "crs-sim-labels.json"
    path.write_text(json.dumps({"sellers": {"best-buy": {"seller_type": "sim"}, "gadget-grove": {"seller_type": "sim"}}}))
    monkeypatch.setenv("CRS_TEST_IDENTITIES_PATH", str(path))
    monkeypatch.setenv("CRS_SIGNAL_CACHE_PATH", str(folder / "crs-signals.json"))
    monkeypatch.delenv("CRS_CACHE_SECRET", raising=False)
