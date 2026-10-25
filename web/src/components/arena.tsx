// web/src/components/arena.tsx
// The Question card (one question put to the arena) and the bout badge. Tokens only, no literal colors.
import { Card, OriginChip } from "./ui";
import { roman } from "@/lib/roman";

export type QuestionProps = {
  question: string;
  bout?: number;
  of?: number;
  status: "open" | "sealed" | "verdict";
  contenders?: number;
  verdict?: { kind: "won" | "knocked"; text: string };
  origin?: string;
};

const PILL = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 font-display text-[12px] font-semibold uppercase tracking-[0.1em]";

function StatusPill({ status, verdict }: { status: QuestionProps["status"]; verdict?: QuestionProps["verdict"] }) {
  const dot = <span className="h-[7px] w-[7px] rounded-full bg-current" aria-hidden />;
  if (status === "open") return <span className={`${PILL} torch bg-accent-soft text-accent`}>{dot}Open</span>;
  if (status === "sealed") return <span className={`${PILL} bg-amber-soft text-amber`}>{dot}Sealed</span>;
  const tone = verdict?.kind === "knocked" ? "bg-coral-soft text-coral" : "bg-mint-soft text-mint";
  return <span className={`${PILL} ${tone}`}>{dot}Verdict</span>;
}

export function Question({ question, bout, of, status, contenders, verdict, origin }: QuestionProps) {
  const eyebrow = bout !== undefined ? `The question · Bout ${roman(bout)}${of !== undefined ? ` of ${roman(of)}` : ""}` : "The question";
  return (
    <Card className="border-t-[3px] border-t-accent">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-display text-[12px] uppercase tracking-[0.14em] text-accent/80">{eyebrow}</p>
        <div className="flex items-center gap-2">
          {origin && <OriginChip origin={origin} />}
          <StatusPill status={status} verdict={verdict} />
        </div>
      </div>
      <h2 className="mt-3 font-display text-[20px] leading-tight text-ink sm:text-[28px]">{question}</h2>
      <div className="my-3 h-px bg-accent/40" aria-hidden />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted">
        {contenders !== undefined && <span>{contenders} {contenders === 1 ? "contender" : "contenders"}</span>}
        {status === "verdict" && verdict && (
          <span className={`font-semibold ${verdict.kind === "won" ? "text-mint" : "text-coral"}`}>
            {verdict.kind === "won" ? "WON" : "KNOCKED OUT"} {verdict.text}
          </span>
        )}
      </div>
    </Card>
  );
}

export type BoutStatus = "waiting" | "in-arena" | "won" | "knocked" | "clash";

const BOUT: Record<BoutStatus, { cls: string; word: string }> = {
  waiting: { cls: "border border-line-2 text-muted", word: "Waiting" },
  "in-arena": { cls: "torch bg-accent-soft text-accent", word: "In the arena" },
  won: { cls: "bg-mint-soft text-mint", word: "WON" },
  knocked: { cls: "bg-coral-soft text-coral", word: "KNOCKED OUT" },
  clash: { cls: "bg-coral-soft text-coral", word: "CLASH" },
};

export function BoutBadge({ status }: { status: BoutStatus }) {
  const b = BOUT[status];
  return <span className={`${PILL} ${b.cls}`}>{b.word}</span>;
}
