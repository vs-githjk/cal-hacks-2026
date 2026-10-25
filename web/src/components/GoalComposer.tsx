"use client";
// The product request: one typed field with optional details, above everything else on the dashboard. It works before
// pairing (the draft is kept through it) and never shows a draft to a different buyer. Two things are not connected and
// say so instead of pretending: sending from this screen (lib/goalRequest.ts GOAL_COMMAND) and voice entry
// (SPEECH_TRANSPORT). Until they are, the working route is to copy the request and send it to the buyer agent in ASI:One.

import { useRef, useState } from "react";
import { ASI_ONE_URL } from "@/lib/agentFeed";
import {
  CONDITIONS,
  EMPTY_DRAFT,
  GoalSubmitError,
  buildGoalRequest,
  draftFor,
  fallbackMessage,
  parseStoredDraft,
  submitGoal,
  type GoalDraft,
  type Problem,
} from "@/lib/goalRequest";
import { Card, Label } from "./ui";

const DRAFT_KEY = "tb-goal-draft";

function readStored() {
  try {
    return parseStoredDraft(sessionStorage.getItem(DRAFT_KEY));
  } catch {
    return null; // storage blocked: the draft just does not survive a reload
  }
}

function writeStored(owner: string | null, draft: GoalDraft) {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ owner, draft }));
  } catch {
    // a per-tab convenience only
  }
}

type Status =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "done"; goalId: string }
  | { kind: "note"; text: string }
  | { kind: "error"; text: string };

const input = "min-h-11 w-full rounded-lg border border-line bg-soft px-3 text-[15px] aria-[invalid=true]:border-coral";

/** buyerId is null before pairing. A draft typed then is adopted by the first buyer to pair; another buyer never sees it. */
export function GoalComposer({ buyerId }: { buyerId: string | null }) {
  const [draft, setDraft] = useState<GoalDraft>(() => {
    const d = draftFor(readStored(), buyerId);
    if (buyerId) writeStored(buyerId, d); // claim a pre-pairing draft, or scrub another buyer's
    return d;
  });
  const [problems, setProblems] = useState<Problem[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [detailsOpen, setDetailsOpen] = useState(false);
  const requestId = useRef<string | null>(null);
  const bad = (f: keyof GoalDraft) => problems.some((p) => p.field === f);
  const detailsBad = bad("cap") || bad("deadline") || bad("conditions");
  const filled = [draft.cap.trim() && `cap ${draft.cap.trim()}`, draft.deadline && `by ${draft.deadline}`, CONDITIONS.filter((c) => draft.conditions.includes(c)).join(", ")].filter(Boolean).join(" · ");

  const change = (next: Partial<GoalDraft>) => {
    const d = { ...draft, ...next };
    setDraft(d);
    writeStored(buyerId, d);
    setProblems([]);
    if (status.kind !== "sending") setStatus({ kind: "idle" });
    requestId.current = null; // a changed request is a new request
  };

  const build = () => {
    requestId.current ??= crypto.randomUUID();
    const built = buildGoalRequest(draft, requestId.current, new Date());
    if (!built.ok) {
      setProblems(built.problems);
      return null;
    }
    setProblems([]);
    return built.request;
  };

  const viaAsiOne = async () => {
    const request = build();
    if (!request) return;
    window.open(ASI_ONE_URL, "_blank", "noopener,noreferrer");
    try {
      await navigator.clipboard.writeText(fallbackMessage(request));
      setStatus({ kind: "note", text: "Copied. Paste it to the buyer agent in ASI:One." });
    } catch {
      setStatus({ kind: "error", text: "Copying is blocked in this browser. Select the request above, copy it, and paste it in ASI:One." });
    }
  };

  const findOffers = async () => {
    if (status.kind === "sending") return; // a second tap while one is in flight does nothing
    const request = build();
    if (!request) return;
    if (buyerId === null) {
      setStatus({ kind: "error", text: "Pair this screen with the buyer below first. Your request is kept." });
      return;
    }
    setStatus({ kind: "sending" });
    try {
      const { goalId } = await submitGoal(request);
      setStatus({ kind: "done", goalId });
      setDraft(EMPTY_DRAFT);
      writeStored(buyerId, EMPTY_DRAFT);
      requestId.current = null;
    } catch (e) {
      setStatus({ kind: "error", text: e instanceof GoalSubmitError ? e.message : "The request could not be sent." });
    }
  };

  return (
    <Card>
      <Label>Find a product</Label>
      <label htmlFor="goal-text" className="mb-1.5 block text-[14px] text-muted">
        What do you want to buy?
      </label>
      <textarea
        id="goal-text"
        value={draft.text}
        onChange={(e) => change({ text: e.target.value })}
        rows={2}
        aria-invalid={bad("text")}
        placeholder="For example: a 1 TB NVMe SSD under $90 by Friday"
        className="min-h-[72px] w-full resize-y rounded-lg border border-line bg-soft px-3 py-2.5 text-[18px] leading-snug aria-[invalid=true]:border-coral"
      />

      <details className="mt-1" open={detailsOpen || detailsBad} onToggle={(e) => setDetailsOpen(e.currentTarget.open)}>
        <summary className="inline-flex min-h-11 cursor-pointer items-center text-[14px] text-muted">
          Details (optional){filled ? `: ${filled}` : ""}
        </summary>
        <div className="grid gap-3 pt-1 sm:grid-cols-[1fr_1fr_2fr]">
          <div>
            <label htmlFor="goal-cap" className="mb-1 block text-[13px] text-muted">Budget cap (dollars, optional)</label>
            <input id="goal-cap" value={draft.cap} onChange={(e) => change({ cap: e.target.value })} inputMode="decimal" autoComplete="off" placeholder="650" aria-invalid={bad("cap")} className={input} />
          </div>
          <div>
            <label htmlFor="goal-deadline" className="mb-1 block text-[13px] text-muted">Needed by (optional)</label>
            <input id="goal-deadline" type="date" value={draft.deadline} onChange={(e) => change({ deadline: e.target.value })} aria-invalid={bad("deadline")} className={input} />
          </div>
          <fieldset aria-invalid={bad("conditions")}>
            <legend className="mb-1 text-[13px] text-muted">Acceptable conditions (optional)</legend>
            <div className="flex flex-wrap gap-x-4">
              {CONDITIONS.map((c) => (
                <label key={c} className="inline-flex min-h-11 items-center gap-2 text-[15px]">
                  <input
                    type="checkbox"
                    className="h-5 w-5"
                    checked={draft.conditions.includes(c)}
                    onChange={(e) => change({ conditions: e.target.checked ? [...draft.conditions, c] : draft.conditions.filter((x) => x !== c) })}
                  />
                  {c}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

      </details>

      {problems.length > 0 && (
        <ul role="alert" className="mt-3 grid gap-1 text-[14px] text-coral">
          {problems.map((p) => (
            <li key={p.field}>{p.message}</li>
          ))}
        </ul>
      )}

      <p id="goal-blocked" className="mt-3 text-[13px] text-muted">
        Not connected yet: Find offers and Speak cannot send from this screen, even after pairing. Copy the request to the buyer agent in ASI:One to start a search.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={viaAsiOne} className="min-h-11 rounded-lg bg-accent px-4 font-medium text-accent-ink">
          Copy and open ASI:One
        </button>
        <button type="button" aria-disabled="true" aria-describedby="goal-blocked" onClick={findOffers} className="min-h-11 rounded-lg border border-line px-4 font-medium text-muted">
          Find offers
        </button>
        <button type="button" aria-disabled="true" aria-describedby="goal-blocked" className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 font-medium text-muted">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <rect x="9" y="3" width="6" height="12" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
          Speak
        </button>
      </div>

      <p role="status" aria-live="polite" className={`mt-2 text-[14px] ${status.kind === "error" ? "text-coral" : ""}`}>
        {status.kind === "sending" && "Sending..."}
        {status.kind === "done" && `Recorded as goal ${status.goalId}. It shows under Active searches once the market lists it.`}
        {(status.kind === "note" || status.kind === "error") && status.text}
      </p>
    </Card>
  );
}
