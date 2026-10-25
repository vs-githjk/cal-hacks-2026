// web/src/components/arena.tsx
// The Question card: the one question a round puts to the arena. Tokens only, no literal colors.
import { Card, OriginChip } from "./ui";

export type QuestionProps = {
  question: string;
  bout?: number;
  of?: number;
  /** none: the market has no round yet (#398). */
  status: "open" | "sealed" | "verdict" | "none" | "loading";
  /** A short line after the status word, like the round's name. */
  detail?: string;
  contenders?: number;
  verdict?: { kind: "won" | "knocked"; text: string };
  origin?: string;
};

const Dot = ({ tone }: { tone: string }) => <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone}`} aria-hidden />;

export function Question({ question, bout, of, status, detail, contenders, verdict, origin }: QuestionProps) {
  const state =
    status === "loading" ? { tone: "bg-muted", word: "Connecting..." }
    : status === "none" ? { tone: "bg-muted", word: "No round yet" }
    : status === "open" ? { tone: "bg-accent", word: "Open for bids" }
    : status === "sealed" ? { tone: "bg-muted", word: "Bids sealed" }
    : { tone: verdict?.kind === "knocked" ? "bg-coral" : verdict ? "bg-mint" : "bg-muted", word: "Decided" };
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px] text-ink-2">
        <span className="inline-flex items-center gap-2">
          <Dot tone={state.tone} />
          {state.word}
          {bout !== undefined && <span className="text-muted">Round {bout}{of !== undefined ? ` of ${of}` : ""}</span>}
          {detail && <span className="text-muted">{detail}</span>}
        </span>
        {origin && <OriginChip origin={origin} />}
      </div>
      <h2 className="mt-3 max-w-[40ch] text-[22px] font-semibold leading-tight tracking-[-0.02em] text-ink sm:text-[28px]">{question}</h2>
      {(contenders !== undefined || verdict) && (
        <p className="mt-3 text-[13.5px] text-muted">
          {contenders !== undefined && <>{contenders} {contenders === 1 ? "seller" : "sellers"} bid</>}
          {verdict && <>{contenders !== undefined && ". "}{verdict.kind === "won" ? <><span className="text-mint">Won</span> by {verdict.text}</> : <span className="text-ink-2">No winner: {verdict.text}</span>}</>}
        </p>
      )}
    </Card>
  );
}
