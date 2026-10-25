# Screen map

> **Version 2 note (Oct 25 2026).** Token values changed; names mostly did not. Every `font-serif` display is now Geist 500 with tight tracking, `royal` is `referee`, `shadow-pop` is `shadow-lift`, `shadow-glow` is `shadow-focus`, and the canvas is Prism's cool #eef3f8. Snippets below were updated by substitution and not re-rendered; treat them as starting points and check them against the previews.

Each route: its job, what it must show (true to the backend today), the components, and a snippet. Snippets are React 19 + Tailwind v4 utilities from the `@theme` block in `handoff.md` (`bg-surface`, `text-muted`, `border-line`, `font-sans`, `rounded-card`). Animation uses `motion` 11 (`import { motion } from "motion/react"`). Every state word comes from the `source` and `status` fields; never derive a label from colour.

Owner key: **V** = Vedant (landing, /start, /buyer*), **A** = Abhinav (/floor), shared otherwise.

| Route | Job | Must show | Components |
| --- | --- | --- | --- |
| `/` (V) | Make a visitor trust it in 10 seconds and start a goal | Hero with one serif headline, three measured numbers (39 of 39, 13 of 20, 9 of 10), the five steps, a "what is real" strip, the agent roster teaser, Seller Kit teaser, "Watch the floor" | Nav, Hero, StatusPill, AgentRoster (3 rows), WindTunnel (numbers), footer with "Sandbox only: test cards, test identities, no real money" |
| `/start` (V) | Capture the goal | Goal, allowance, phone, owned parts (SIM rig), the sentence about the call code | GoalCard, Nav |
| `/buyer` (V) | The buyer home: the one live round | Round number and part, seller count, sealed pills, closes-in timer, last referee call, the ASI:One panel on the right (1440) or as a sheet (390) | DecisionCard (live variant), ChatPip (panel), StatusPill |
| `/buyer/decisions` (V) | Every round as a ledger | Winner hero number, each loser with reason and source link, honesty labels, the ranking rule line | DecisionCard |
| `/buyer/purchases` (V) | Receipts | One ReceiptCard per part, Stripe test mode, mandate, signature line, settlement pending, SIM shipping | ReceiptCard |
| `/buyer/agents` (V) | The roster | Nine agents, job, heartbeat, LIVE/SIM/MIRROR, avatar | AgentRoster |
| approval (sheet over any /buyer route) (V) | The call | Amount vs allowance, the spoken word pair, four states | ApprovalCall |
| `/sell` (V, later) | Seller Kit onboarding | Four steps, floors per condition, the config and command, the SIM label | SellerKit |
| `/seller/[id]` | A seller's loss reports | Banded gap, reason, source; never a rival's price | DecisionCard rows, StatusPill |
| `/market` | Public market state | Rounds in progress, sealed counts, no money or identity (public view) | StatusPill, table |
| `/lot` | Lot Wall | One real request, the wall, the price ladder, "planned, not built" | LotWall |
| `/floor` (A) | The arcade | Ring, buyer, sellers, referee, Shield, checker, HUD, ledger strip, PiP | FloorPreview, ChatPip (PiP) |

## Concept coverage

Where each concept Vidyut listed appears, so none is only in a doc:

- Sandbox (Stripe test mode): ReceiptCard "Paid · test mode", footer line, Hero mock row.
- Wind tunnel: WindTunnel card on `/` and `/market`.
- Lot Wall: `/lot`, LotWall.
- Sealed knockout rounds: DecisionCard, the floor, `/buyer` live round.
- Shield injection screen: floor round 2 (BLOCKED), DecisionCard "Blocked by Shield" row with the rules that fired, AgentRoster row.
- CRS referee: `referee` pill on every decision and receipt, the referee sprite and call banner on the floor, "verified_stable" wording from the Oct 24 sandbox run.
- Checker (fit and recalls): "Fit confirmed, 304 mm", "No recall, CPSC by brand", floor round 3, the 39 of 39 number.
- Bright Data live re-check: the "Price" caution line on DecisionCard ("runs when its key is set"), ReceiptCard omits it unless it ran.
- Apify Actors: `/market` source line "Listings: dated snapshots via Apify (Best Buy, Micro Center, B&H, Newegg; 12 Central Computers rows)", Seller Agent-Readiness Report link on `/sell`.
- Phone approval code: ApprovalCall, floor end card, Hero copy.
- Per-part receipts: ReceiptCard, one per part.
- Real vs simulated: StatusPill honesty row, the "what is real" strip on `/`, labels on every card.
- Agent roster: AgentRoster, avatars from `agents/avatars/`.
- Seller Kit: SellerKit on `/sell`.
- Measured results: WindTunnel card, Hero proof row.

## Snippets

### Status pill

```tsx
const tone = {
  live: "bg-pulse-soft text-pulse", sealed: "bg-slate-soft text-slate",
  eaten: "bg-coral-soft text-coral", blocked: "bg-coral-soft text-coral", vetoed: "bg-coral-soft text-coral", denied: "bg-coral-soft text-coral",
  approved: "bg-mint-soft text-mint", paid: "bg-mint-soft text-mint", verified: "bg-mint-soft text-mint",
  sim: "bg-amber-soft text-amber", caution: "bg-amber-soft text-amber", mirror: "bg-slate-soft text-slate", referee: "bg-referee-soft text-referee",
} as const;

export function Pill({ kind, children, pulse = false }: { kind: keyof typeof tone; children: React.ReactNode; pulse?: boolean }) {
  return (
    <span className={`inline-flex h-6 items-center gap-1.5 rounded-pill px-2.5 text-[12px] font-medium uppercase tracking-[0.04em] whitespace-nowrap ${tone[kind]}`}>
      {pulse && <PulseDot />}
      {children}
    </span>
  );
}

export function PulseDot() {
  return (
    <span className="relative inline-block size-2 rounded-full bg-current">
      <span className="absolute inset-0 rounded-full bg-current opacity-50 motion-safe:animate-[tb-pulse_1800ms_cubic-bezier(0.2,0.8,0.2,1)_infinite]" />
    </span>
  );
}
```

### Card and hero number

```tsx
export function Card({ active, className = "", children }: { active?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: [0.2, 0.8, 0.2, 1] }}
      className={`rounded-card border bg-surface p-4 shadow-card md:p-5 ${active ? "border-pulse shadow-focus" : "border-line"} ${className}`}
    >{children}</motion.section>
  );
}

export function HeroNumber({ value }: { value: number }) {
  // Count-up once on mount, 900 ms ease-out; static under reduced motion.
  const reduce = useReducedMotion();
  const mv = useMotionValue(reduce ? value : 0);
  const text = useTransform(mv, (v) => v.toLocaleString("en-US", { style: "currency", currency: "USD" }));
  useEffect(() => { if (!reduce) animate(mv, value, { duration: 0.9, ease: [0.2, 0.8, 0.2, 1] }); }, [value]);
  return <motion.div className="font-sans text-[44px] leading-[48px] tabular-nums md:text-[56px] md:leading-[60px]">{text}</motion.div>;
}
```

### Decision row (loser with reason and source)

```tsx
type Bid = { seller: string; price: number; color: "ghost-1" | "ghost-2" | "ghost-3" | "ghost-4"; status: "eaten" | "blocked" | "vetoed" | "winner"; reason: string; sourceHref?: string; source: "LIVE" | "MIRROR" | "SIM" };

export function BidRow({ b }: { b: Bid }) {
  const out = b.status !== "winner";
  return (
    <div className="grid grid-cols-[8px_1fr_auto] items-start gap-3 border-t border-line py-3 first:border-t-0">
      <i className={`mt-1.5 size-2 rounded-full bg-${b.color}`} />
      <div>
        <div className="flex flex-wrap items-center gap-2">{b.seller} <Pill kind={b.status === "winner" ? "verified" : b.status}>{b.status === "eaten" ? "Eaten · price" : b.status}</Pill> <Pill kind={b.source.toLowerCase() as "live" | "mirror" | "sim"}>{b.source}</Pill></div>
        <div className="text-[13px] leading-[18px] text-muted">{b.reason} {b.sourceHref && <a className="text-pulse" href={b.sourceHref}>source</a>}</div>
      </div>
      <div className={`font-mono text-[15px] font-medium tabular-nums ${out ? "text-muted line-through" : ""}`}>${b.price.toFixed(2)}</div>
    </div>
  );
}
```

### Approval code

```tsx
export function ApprovalCode({ words }: { words: [string, string] }) {
  return (
    <div className="rounded-md bg-surface-2 p-4 text-center">
      <div className="mb-1.5 text-[12px] font-medium uppercase tracking-[0.06em] text-muted">Say this word pair, then "approve"</div>
      <div className="font-mono text-[28px] leading-8 font-medium tracking-[0.04em]">{words.join(" ")}</div>
    </div>
  );
}
```

### Agent heartbeat row

```tsx
export function AgentRow({ a }: { a: { name: string; job: string; initials: string; ring: string; avatar?: string; beat: string; idle?: boolean } }) {
  return (
    <div className="grid grid-cols-[36px_1fr] items-center gap-3 border-t border-line py-3 first:border-t-0 md:grid-cols-[36px_1fr_auto]">
      {a.avatar ? <img src={a.avatar} alt="" className="size-9 rounded-full border-2" style={{ borderColor: `var(--${a.ring})` }} />
        : <span className="grid size-9 place-items-center rounded-full border-2 bg-surface-2 text-[12px] font-semibold" style={{ borderColor: `var(--${a.ring})` }}>{a.initials}</span>}
      <div><div>{a.name}</div><div className="text-[13px] leading-[18px] text-muted">{a.job}</div></div>
      <div className={`flex items-center gap-2 font-mono text-[12px] md:col-auto col-start-2 ${a.idle ? "text-slate" : "text-pulse"}`}>{a.idle ? <span className="size-2 rounded-full bg-current" /> : <PulseDot />}<span className="text-muted">{a.beat}</span></div>
    </div>
  );
}
```

### ASI:One picture-in-picture (floor) and panel (outside)

```tsx
export function ChatPip({ messages }: { messages: { from: "you" | "agent"; text: string }[] }) {
  return (
    <aside aria-label="ASI:One chat, mirrored" className="absolute right-4 top-3.5 w-[22%] min-w-[128px] max-w-[220px] overflow-hidden rounded-xl border border-white/20 bg-[#121620]/92 shadow-lift">
      <div className="flex items-center gap-1.5 border-b border-white/10 px-3 py-2.5 font-mono text-[10px] uppercase tracking-[0.06em] text-[#b7bfcc]"><span className="size-1.5 rounded-full bg-shield shadow-[0_0_0_3px_rgba(111,147,255,0.25)]" />ASI:One · the buyer</div>
      <div className="grid gap-1.5 p-3">{messages.slice(-3).map((m, i) => <div key={i} className={`max-w-[95%] rounded-[10px] px-2 py-1.5 text-[11px] leading-[15px] ${m.from === "you" ? "justify-self-end bg-shield text-[#0b0d12]" : "bg-[#1a1f2b] text-[#edf0f5]"}`}>{m.text}</div>)}</div>
    </aside>
  );
}
```

### Empty, loading, error (every demo-path screen)

```tsx
export const Empty = ({ text, action }: { text: string; action?: React.ReactNode }) => <div className="rounded-card border border-dashed border-line-2 p-6 text-center text-[13px] text-muted">{text}<div className="mt-3">{action}</div></div>;
export const Skeleton = ({ h = 120 }: { h?: number }) => <div aria-busy className="rounded-card bg-surface-2 motion-safe:animate-pulse" style={{ height: h }} />;
export const ErrorLine = ({ reason, href }: { reason: string; href?: string }) => <div className="flex items-center gap-2 text-[13px]"><Pill kind="denied">Error</Pill><span className="text-ink-2">{reason}</span>{href && <a className="text-pulse" href={href}>source</a>}</div>;
```
