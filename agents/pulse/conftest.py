"""Pulse tests never write into the repo's .run folder: the shared pulse file and the saved rounds go to a temp folder unless a test sets its own."""
import pytest


@pytest.fixture(autouse=True)
def _pulse_files_in_tmp(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("pulse_files")
    monkeypatch.setenv("PULSE_PUBLIC_PATH", str(base / "public" / "latest.json"))
    monkeypatch.setenv("PULSE_ROUND_DIR", str(base / "rounds"))
