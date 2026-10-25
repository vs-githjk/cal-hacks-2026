"use client";
// The two sponsor proof lines under a locked part on the build panel: Bright Data's re-check ("checked Ns ago", or why the price was
// not re-read) and Tiger Data's 7 and 30 day prices. The text is built in lib/proof.ts; this only draws it and ticks the clock.
import { useEffect, useState } from "react";
import { proofFor, type ProofLine } from "@/lib/proof";
import type { BuildResult } from "@/lib/build";
import { OriginChip } from "./ui";

function Line({ line, testId }: { line: ProofLine; testId: string }) {
  return (
    <li data-testid={testId} data-read={line.read} className={line.read ? "text-ink-2" : "text-muted"}>
      <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle ${line.read ? "bg-mint" : "bg-line"}`} aria-hidden />
      {line.text} <OriginChip origin={line.origin} />
    </li>
  );
}

export function ProofLines({ build, part }: { build: BuildResult; part: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const proof = proofFor(build, part, now);
  if (!proof) return null; // no champion yet, or the built-in sample: nothing to prove
  return (
    <ul className="col-span-full mt-1.5 grid gap-0.5 pl-[88px] text-[12px]" aria-label="Sponsor proof for this part">
      <Line line={proof.bright} testId={`proof-bright-${part}`} />
      <Line line={proof.tiger} testId={`proof-tiger-${part}`} />
    </ul>
  );
}
