"""merge_dryrun.sh tests: throwaway git repo in tmp_path, no network. Run: python3 -m pytest scripts/tests/test_merge_dryrun.py -q"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "merge_dryrun.sh"
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def commit_file(repo: Path, branch: str, name: str, text: str) -> None:
    git(repo, "checkout", "-q", branch)
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"{branch}: {name}")


def start_branch(repo: Path, name: str) -> None:
    git(repo, "checkout", "-q", "-b", name, "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("one\ntwo\nthree\n")
    (r / "b.txt").write_text("keep\n")
    git(r, "add", "a.txt", "b.txt")
    git(r, "commit", "-q", "-m", "base")
    start_branch(r, "conflict-1")
    commit_file(r, "conflict-1", "a.txt", "one\nTWO from one\nthree\n")
    start_branch(r, "conflict-2")
    commit_file(r, "conflict-2", "a.txt", "one\nTWO from two\nthree\n")
    start_branch(r, "clean-3")
    commit_file(r, "clean-3", "c.txt", "new file\n")
    git(r, "checkout", "-q", "main")
    return r


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, env=ENV)


def snapshot(repo: Path) -> tuple[str, str, str, str]:
    return (
        git(repo, "for-each-ref"),
        git(repo, "rev-parse", "HEAD"),
        git(repo, "symbolic-ref", "HEAD"),
        git(repo, "status", "--porcelain"),
    )


def step_lines(out: str, branch: str) -> list[str]:
    """The block for one branch: its 'step' line plus the indented paths under it."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("step ") and f" {branch} " in line + " ":
            block = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("  "):
                    block.append(nxt)
                else:
                    break
            return block
    raise AssertionError(f"no step for {branch} in:\n{out}")


def test_reports_exactly_the_conflicted_path_exit_0_and_changes_nothing(repo: Path) -> None:
    before = snapshot(repo)
    res = run(repo, "main", "conflict-1", "conflict-2", "clean-3")
    assert res.returncode == 0, res.stderr
    assert snapshot(repo) == before
    assert "CONFLICT" not in "\n".join(step_lines(res.stdout, "conflict-1"))
    assert step_lines(res.stdout, "conflict-2")[1:] == ["  a.txt"]
    assert "CONFLICT" in step_lines(res.stdout, "conflict-2")[0]
    assert "CONFLICT" not in "\n".join(step_lines(res.stdout, "clean-3"))
    assert "1 of 3 steps conflict" in res.stdout
    assert (repo / "a.txt").read_text() == "one\ntwo\nthree\n"


def test_a_conflict_against_the_running_result_not_the_base_is_found(repo: Path) -> None:
    # both branches ADD new.txt: neither conflicts with main, the second conflicts with the first
    start_branch(repo, "adds-1")
    commit_file(repo, "adds-1", "new.txt", "from one\n")
    start_branch(repo, "adds-2")
    commit_file(repo, "adds-2", "new.txt", "from two\n")
    git(repo, "checkout", "-q", "main")
    alone = run(repo, "main", "adds-2")
    assert "0 of 1 steps conflict" in alone.stdout
    both = run(repo, "main", "adds-1", "adds-2")
    assert step_lines(both.stdout, "adds-2")[1:] == ["  new.txt"]


def test_missing_branch_is_named_and_skipped_and_the_rest_still_run(repo: Path) -> None:
    res = run(repo, "main", "no-such-branch", "conflict-1", "conflict-2")
    assert res.returncode == 0, res.stderr
    assert "NOT FOUND" in "\n".join(step_lines(res.stdout, "no-such-branch"))
    assert step_lines(res.stdout, "conflict-2")[1:] == ["  a.txt"]
    assert "1 not found" in res.stdout


def test_an_already_merged_branch_is_clean_and_says_so(repo: Path) -> None:
    git(repo, "merge", "-q", "--no-edit", "clean-3")
    res = run(repo, "main", "clean-3")
    assert "already contained" in "\n".join(step_lines(res.stdout, "clean-3"))


def test_unrelated_history_is_an_error_step_not_a_crash(repo: Path) -> None:
    git(repo, "checkout", "-q", "--orphan", "island")
    git(repo, "rm", "-rfq", ".")
    (repo / "z.txt").write_text("z\n")
    git(repo, "add", "z.txt")
    git(repo, "commit", "-q", "-m", "island")
    git(repo, "checkout", "-q", "main")
    res = run(repo, "main", "island", "clean-3")
    assert res.returncode == 0, res.stderr
    assert "ERROR" in "\n".join(step_lines(res.stdout, "island"))
    assert "CONFLICT" not in "\n".join(step_lines(res.stdout, "clean-3"))


def test_usage_and_bad_base_exit_2(repo: Path) -> None:
    assert run(repo).returncode == 2
    assert run(repo, "main").returncode == 2
    bad = run(repo, "no-such-base", "conflict-1")
    assert bad.returncode == 2
    assert "base" in bad.stderr


def test_script_never_names_a_ref_writing_or_checkout_command() -> None:
    text = SCRIPT.read_text()
    for banned in ("git merge ", "git checkout", "git switch", "git reset", "update-ref", "git push", "git rebase", "git commit "):
        assert banned not in text, banned
    assert chr(0x2014) not in text and chr(0x2013) not in text


# docs/MERGE_0800.md: the command it tells you to run must be the table above it (the first version listed six
# squash-merged Lane C branches the table had dropped, so the script printed 8 of 11 conflicts, not 1 of 5).
def _merge_page() -> str:
    return (Path(__file__).resolve().parents[2] / "docs" / "MERGE_0800.md").read_text()


def _page_command(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines() if ln.startswith("bash scripts/merge_dryrun.sh ")]
    assert len(lines) == 1
    return lines[0].split()[2:]


def test_merge_page_command_walks_exactly_the_tables_branches() -> None:
    text = _merge_page()
    args = _page_command(text)
    assert args[0] == "origin/main"
    rows = [ln.split("|")[2].strip().split()[0] for ln in text.splitlines()
            if ln.startswith("| ") and ln.split("|")[1].strip().isdigit()]
    assert args[1:] == rows
    assert f"of {len(rows)} steps conflicts" in text


def test_merge_page_command_names_no_squash_merged_lane_c_branch() -> None:
    args = _page_command(_merge_page())
    for gone in ("lane-c-118-snapshot-refresh", "lane-c-125-power-fit", "lane-c-c14-three-way-match",
                 "lane-c-136-history-source", "lane-c-141-price-position", "lane-c-140-real-catch"):
        assert not any(gone in a for a in args), gone


def test_merge_page_says_where_the_script_lives() -> None:
    text = _merge_page()
    assert "from any checkout of the repo" not in text
    assert "scripts/merge_dryrun.sh" in text and "a checkout of lane-d-night2" in text
