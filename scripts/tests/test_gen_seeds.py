"""scripts/gen_seeds.py: fresh private seeds for the agents that still need one, appended to an env file, never printed,
never overwriting a seed that is already there. Temp files only: no real env file is read or written."""
import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "gen_seeds.py"
_spec = importlib.util.spec_from_file_location("gen_seeds", SCRIPT)
G = importlib.util.module_from_spec(_spec)
sys.modules["gen_seeds"] = G
_spec.loader.exec_module(G)

NAMES = ["CALLER_AGENT_SEED", "SHIELD_AGENT_SEED", "PULSE_AGENT_SEED", "SELLER_5_AGENT_SEED", "SELLER_6_AGENT_SEED"]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def values(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2).strip("'\"")
    return out


def run(path, capsys, *extra):
    code = G.main([str(path), *extra])
    cap = capsys.readouterr()
    return code, cap.out + cap.err


def test_the_five_names_are_the_ones_the_brief_names():
    assert list(G.SEED_NAMES) == NAMES


def test_an_empty_file_gets_five_distinct_64_hex_seeds(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("")
    code, out = run(env, capsys)
    got = values(env)
    assert code == 0 and sorted(got) == sorted(NAMES)
    assert all(HEX64.match(v) for v in got.values()) and len(set(got.values())) == 5


def test_no_seed_value_is_ever_printed(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("OTHER=1\n")
    code, out = run(env, capsys)
    assert code == 0
    for name in NAMES:
        assert values(env)[name] not in out
    assert not re.search(r"[0-9a-f]{32}", out)
    for name in NAMES:
        assert name in out                                               # names are said, values never


def test_a_seed_that_is_already_there_is_never_overwritten_and_the_file_is_otherwise_untouched(tmp_path, capsys):
    env = tmp_path / "agents.env"
    original = "# agents\nCALLER_AGENT_SEED=mine-keep-this-one-0123456789\nexport PULSE_AGENT_SEED='quoted private seed value'\nANTHROPIC_API_KEY=sk-test\n"
    env.write_text(original)
    code, out = run(env, capsys)
    text = env.read_text()
    assert code == 0 and text.startswith(original)                        # byte for byte, new lines only after it
    assert values(env)["CALLER_AGENT_SEED"] == "mine-keep-this-one-0123456789" and values(env)["PULSE_AGENT_SEED"] == "quoted private seed value"
    assert text.count("CALLER_AGENT_SEED=") == 1 and text.count("PULSE_AGENT_SEED=") == 1
    assert re.search(r"kept\s+CALLER_AGENT_SEED", out) and re.search(r"kept\s+PULSE_AGENT_SEED", out)
    assert "mine-keep" not in out and "quoted private" not in out


def test_a_second_run_changes_nothing(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("A=1\n")
    run(env, capsys)
    once = env.read_text()
    code, out = run(env, capsys)
    assert code == 0 and env.read_text() == once and "added" not in out


def test_an_alias_seed_counts_as_set_because_the_agent_reads_it(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("SHIELD_SEED=alias-private-seed-value-123\nSELLER_5_SEED=another-alias-private-seed-1\n")
    run(env, capsys)
    got = values(env)
    assert "SHIELD_AGENT_SEED" not in got and "SELLER_5_AGENT_SEED" not in got      # adding one would change that agent's address
    assert {"CALLER_AGENT_SEED", "PULSE_AGENT_SEED", "SELLER_6_AGENT_SEED"} <= set(got)


def test_an_empty_placeholder_is_filled_in_place_and_a_comment_is_not_a_seed(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("CALLER_AGENT_SEED=\nSHIELD_AGENT_SEED=''\n# PULSE_AGENT_SEED=old-commented-value\nZ=1\n")
    run(env, capsys)
    lines = env.read_text().splitlines()
    assert HEX64.match(lines[0].split("=", 1)[1]) and HEX64.match(lines[1].split("=", 1)[1])
    assert lines[2] == "# PULSE_AGENT_SEED=old-commented-value" and lines[3] == "Z=1"
    assert HEX64.match(values(env)["PULSE_AGENT_SEED"])
    assert env.read_text().count("CALLER_AGENT_SEED=") == 1


def test_a_public_dev_seed_is_kept_and_flagged_not_replaced(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("CALLER_AGENT_SEED=tech-bazaar-caller-dev\n")
    code, out = run(env, capsys)
    assert code == 0 and values(env)["CALLER_AGENT_SEED"] == "tech-bazaar-caller-dev"
    assert "CALLER_AGENT_SEED" in out and "public" in out


def test_a_missing_file_is_created_private(tmp_path, capsys):
    env = tmp_path / "new" / "agents.env"
    code, _ = run(env, capsys)
    assert code == 0 and stat.S_IMODE(env.stat().st_mode) == 0o600 and len(values(env)) == 5


def test_an_existing_files_permissions_are_kept(tmp_path, capsys):
    env = tmp_path / "agents.env"
    env.write_text("A=1")                                                # no trailing newline
    env.chmod(0o640)
    run(env, capsys)
    assert stat.S_IMODE(env.stat().st_mode) == 0o640 and env.read_text().startswith("A=1\nCALLER_AGENT_SEED=")


@pytest.mark.parametrize("name", [".env.example", "agents.env.example", "ENV.EXAMPLE"])
def test_it_refuses_a_tracked_example_file(tmp_path, capsys, name):
    env = tmp_path / name
    env.write_text("A=1\n")
    code, out = run(env, capsys)
    assert code == 2 and env.read_text() == "A=1\n" and "example" in out


def test_it_refuses_a_directory_and_prints_no_traceback(tmp_path, capsys):
    code, out = run(tmp_path, capsys)
    assert code == 2 and "Traceback" not in out


def test_it_refuses_no_argument():
    out = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert out.returncode == 2 and "env file" in (out.stdout + out.stderr).lower()


def test_the_command_line_run_prints_names_only(tmp_path):
    env = tmp_path / "agents.env"
    out = subprocess.run([sys.executable, str(SCRIPT), str(env)], capture_output=True, text=True)
    assert out.returncode == 0 and all(n in out.stdout for n in NAMES)
    assert not any(v in out.stdout + out.stderr for v in values(env).values())
    assert os.path.exists(env)
