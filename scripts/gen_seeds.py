#!/usr/bin/env python3
"""Give the agents that still need a private seed one, without ever showing it.

    python3 scripts/gen_seeds.py agents/.env

For each of CALLER_AGENT_SEED, SHIELD_AGENT_SEED, PULSE_AGENT_SEED, SELLER_5_AGENT_SEED and SELLER_6_AGENT_SEED that is missing
from the env file, it appends `NAME=<64 random hex characters>` (secrets.token_hex(32)). It prints only the NAMES it added or
kept, never a value. A seed that is already there is never overwritten, because a seed is an agent's identity: replacing it
changes that agent's Agentverse address. Specifically:
  - a name with a value is kept (a public *-dev default is kept too, and flagged: the agent refuses mailbox mode with it);
  - SHIELD_SEED and SELLER_5_SEED count as set for SHIELD_AGENT_SEED and SELLER_5_AGENT_SEED, because agents/common.py reads them,
    and adding the other name would take precedence and change that agent's address;
  - a name that is present but empty (a placeholder) is filled on its own line; a commented-out line is not a seed;
  - a missing file is created with mode 0600; an existing file keeps its mode; an `.example` file is refused.
Stdlib only. The file is rewritten through a temporary file in the same folder and swapped in, so a failure never leaves half of it.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
import tempfile
from pathlib import Path

SEED_NAMES = ("CALLER_AGENT_SEED", "SHIELD_AGENT_SEED", "PULSE_AGENT_SEED", "SELLER_5_AGENT_SEED", "SELLER_6_AGENT_SEED")
ALIASES = {"SHIELD_AGENT_SEED": "SHIELD_SEED", "SELLER_5_AGENT_SEED": "SELLER_5_SEED"}   # agents/common.py reads these too
LINE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)\s*$")


def _value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1].strip()
    return raw.split(" #", 1)[0].strip()      # an unquoted value ends at a trailing comment


def parse(lines: list[str]) -> dict[str, tuple[int, str]]:
    """{NAME: (line index, value)} for each assignment line (a commented-out line is none)."""
    out: dict[str, tuple[int, str]] = {}
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(2)] = (i, _value(m.group(4)))
    return out


def plan(lines: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """(new lines, [(status, NAME)]) where status is added, filled, kept or public. Seeds are made here and only written into lines."""
    found = parse(lines)
    out, report = list(lines), []
    for name in SEED_NAMES:
        alias = ALIASES.get(name)
        existing = found.get(name)
        if existing is None and alias and found.get(alias, (0, ""))[1]:
            report.append(("kept", f"{alias} (counts for {name})"))
            continue
        if existing and existing[1]:
            report.append(("public" if existing[1].endswith("-dev") else "kept", name))
            continue
        seed = secrets.token_hex(32)
        if existing:
            m = LINE.match(out[existing[0]])
            out[existing[0]] = f"{m.group(1)}{name}{m.group(3)}{seed}"
            report.append(("filled", name))
        else:
            out.append(f"{name}={seed}")
            report.append(("added", name))
    return out, report


def write(path: Path, lines: list[str]) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".gen_seeds_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


MESSAGES = {"added": "added   {}", "filled": "filled  {} (it was empty)", "kept": "kept    {} (already set, not touched)",
            "public": "kept    {} (a PUBLIC dev seed: the agent refuses Agentverse mailbox mode with it; delete that line and run this again)"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    usage = __doc__.split("\n\n")[0] + "\nusage: gen_seeds.py <env file>   (give the env file to append to)"
    if args in (["-h"], ["--help"]):
        print(usage)
        return 0
    if len(args) != 1:
        print(usage, file=sys.stderr)
        return 2
    path = Path(args[0]).expanduser()
    if path.name.lower().endswith(".example"):
        print(f"refusing {path.name}: an example file is tracked in git, a seed written there would be published", file=sys.stderr)
        return 2
    if path.is_dir():
        print(f"{path} is a folder, not an env file", file=sys.stderr)
        return 2
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = text.splitlines()
        new, report = plan(lines)
        if new != lines:
            path.parent.mkdir(parents=True, exist_ok=True)
            write(path, new)
    except (OSError, UnicodeDecodeError) as e:
        print(f"could not update {path}: {type(e).__name__}", file=sys.stderr)       # never the file's content
        return 2
    for status, name in report:
        print(MESSAGES[status].format(name))
    print(f"\n{sum(1 for s, _ in report if s in ('added', 'filled'))} seed(s) written to {path}; values are not shown. Never commit this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
