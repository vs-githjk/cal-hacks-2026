"""Second blind held-out Shield set (Lane C, issue #157). SIM.

    python3 -m sim.heldout2 --file /path/to/heldout2.jsonl      # runs Shield, writes sim/RESULTS-heldout2.md
    python3 -m sim.heldout2 --file /Users/anoopibrampur/calhacks/overnight/heldout3.jsonl --seal sim/attacks/HELDOUT3.sha256 --out sim/RESULTS-heldout3.md

heldout2 is EXPOSED (accidental push 2026-10-24), not blind. heldout3 lives outside the repo and only its hash is committed.

The set (20 seller-side attacks in new styles and 10 honest listings that look suspicious) is sealed: only its sha256 is committed
(sim/attacks/HELDOUT2.sha256). The file stays off the repo until Lane D asks for the measurement. The first run is the headline;
later runs are appended below it and marked not blind. Shield is called through shield.bench (local rules, no classifier).
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from shield.bench import bench

HERE = Path(__file__).resolve().parent
SEAL = HERE / "attacks" / "HELDOUT2.sha256"
OUT = HERE / "RESULTS-heldout2.md"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sealed_hash(seal: Path = SEAL) -> str | None:
    return Path(seal).read_text().split()[0] if Path(seal).exists() else None


def run(path: Path, out: Path = OUT, screen_fn=None, seal: Path = SEAL) -> str:
    """Run the set, write or extend the results file, return the section that was added."""
    res = bench({"heldout2": path}, **({"screen_fn": screen_fn} if screen_fn else {}))["heldout2"]
    digest, sealed = sha256_of(path), sealed_hash(seal)
    first = not out.exists()
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, cwd=HERE).strip()
    except Exception:
        sha = "unknown"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    seal = "matches the sealed sha256" if digest == sealed else f"DOES NOT match the sealed sha256 ({sealed}); the set changed"
    head = "## First run (headline, blind)" if first else f"## Rerun {when} (not blind)"
    section = (f"{head}\n\nRun {when} at git {sha}. File sha256 {digest} {seal}. Shield: local rules, no classifier. SIM.\n\n"
               f"| attacks | stopped | block rate | clean | false blocks | p95 ms |\n|---|---|---|---|---|---|\n"
               f"| {res['attacks']} | {res['attacks'] - len(res['missed'])} | {res['block_rate']:.0%} | {res['clean']} | "
               f"{len(res['false_blocks'])} | {res['p95_ms']} |\n\nMissed: {', '.join(res['missed']) or 'none'}. "
               f"False blocks: {', '.join(res['false_blocks']) or 'none'}. Errors: {', '.join(res['errors']) or 'none'}.\n")
    if first:
        out.write_text("# Second blind held-out Shield set (SIM)\n\nWritten by Lane C without reading Shield's rules or corpus; never tuned on. "
                       "Quote the first run only as the blind number; reruns after any rule change are not blind.\n\n" + section)
    else:
        out.write_text(out.read_text() + "\n" + section)
    return section


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--seal", default=str(SEAL), help="file holding the committed sha256 (sim/attacks/HELDOUT3.sha256 for heldout3)")
    ap.add_argument("--out", default=str(OUT), help="results file (sim/RESULTS-heldout3.md for heldout3)")
    a = ap.parse_args()
    print(run(Path(a.file), out=Path(a.out), seal=Path(a.seal)))


if __name__ == "__main__":
    main()
