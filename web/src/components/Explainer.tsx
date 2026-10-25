// web/src/components/Explainer.tsx
// The plain-language pitch for a first-time visitor: what Fish Market is, how the five beats work, and what
// each side (buyer, seller) gets out of it. Sits between the hero and the live Corral demo on the home page.
import Link from "next/link";
import type { ReactNode, SVGProps } from "react";

function Icon({ children, ...props }: SVGProps<SVGSVGElement> & { children: ReactNode }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="h-7 w-7" {...props}>
      {children}
    </svg>
  );
}

const GoalIcon = () => <Icon><circle cx="16" cy="16" r="11" /><circle cx="16" cy="16" r="6" /><circle cx="16" cy="16" r="1.4" fill="currentColor" stroke="none" /></Icon>;
const SealedIcon = () => <Icon><rect x="6" y="13" width="20" height="14" rx="2.5" /><path d="M9 13 16 7l7 6" /><circle cx="16" cy="19" r="2.2" /></Icon>;
const ShieldIcon = () => <Icon><path d="M16 5 26 9v8c0 6-4.5 9.5-10 10-5.5-.5-10-4-10-10V9Z" /><path d="M12 16.5 15 19.5 20.5 13" /></Icon>;
const PhoneIcon = () => <Icon><path d="M9 5h4l2 5-3 2a14 14 0 0 0 6 6l2-3 5 2v4c0 1.6-1.4 2.8-3 2.6C13.6 25.3 7 18.7 6.2 10.3 6 8.6 7.2 7.2 9 7.2Z" /></Icon>;
const ReportIcon = () => <Icon><path d="M9 4h10l5 5v19H9Z" /><path d="M19 4v5h5" /><path d="M12.5 17.5 15 20l5-6" /></Icon>;
const SearchIcon = () => <Icon><circle cx="14" cy="14" r="8.5" /><path d="M20.5 20.5 27 27" /></Icon>;
const StoreIcon = () => <Icon><path d="M5 11 8 5h16l3 6" /><path d="M5 11v15h22V11" /><path d="M13 26v-8h6v8" /><path d="M5 11a4 4 0 0 0 8 0 4 4 0 0 0 8 0 4 4 0 0 0 8 0" /></Icon>;

const BEATS: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <GoalIcon />, title: "Tell it the goal", text: "A product, a price cap, a deadline. “This GPU, under $800, by Friday.” No browsing required." },
  { icon: <SealedIcon />, title: "Sellers bid, sealed", text: "Seller agents bid in one sealed round. Nobody sees another bid until it closes, so nobody games the price." },
  { icon: <ShieldIcon />, title: "Your advocate checks every bid", text: "It vetoes the cheapest bid when it's a trap, and shows you the page that proves it." },
  { icon: <PhoneIcon />, title: "It calls you before spending big", text: "Above your allowance, your agent calls. You approve one exact deal, out loud, or you say no." },
  { icon: <ReportIcon />, title: "Losers get a reason, not silence", text: "Every seller that loses gets a report: how far off, why, and what to change next time." },
];

export function HowItWorks() {
  return (
    <section aria-label="How it works">
      <h2 className="text-center font-display text-[clamp(26px,3.4vw,38px)] font-normal">How the market works</h2>
      <p className="mx-auto mt-2 max-w-[60ch] text-center text-[17px] text-ink-2">
        Five steps, every time. Nothing is paid until you say the word.
      </p>
      <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {BEATS.map((b, i) => (
          <li key={b.title} className="card flex flex-col gap-3 p-5">
            <div className="flex items-center justify-between">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-soft text-ink">{b.icon}</span>
              <span className="font-mono text-[13px] font-semibold text-muted">{String(i + 1).padStart(2, "0")}</span>
            </div>
            <h3 className="text-[17px] font-semibold tracking-[-0.01em]">{b.title}</h3>
            <p className="text-[14.5px] text-muted">{b.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function Sides() {
  return (
    <section aria-label="For buyers and sellers" className="grid gap-4 sm:grid-cols-2">
      <div className="card flex flex-col gap-4 p-6">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent text-accent-ink">
          <SearchIcon />
        </span>
        <h3 className="text-[22px] font-semibold tracking-[-0.01em]">If you&apos;re buying</h3>
        <p className="text-[16px] text-ink-2">
          Say what you need once. Your agent hunts, sellers bid against each other for your business, and your
          advocate catches the scams before you ever see the listing. You only act when it calls.
        </p>
        <ul className="grid gap-2 text-[15px] text-ink-2">
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>Never overpay: sellers compete in a sealed round, so the price is the real price.</li>
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>Never get scammed: every claim is checked against the live listing, with a source.</li>
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>Never lose control: nothing is paid without your spoken approval.</li>
        </ul>
        <Link href="/buyer" className="btn mt-auto inline-flex min-h-12 w-fit items-center gap-2 rounded-full bg-accent px-6 text-[15px] font-semibold text-accent-ink">
          Open the buyer screen <span aria-hidden>→</span>
        </Link>
      </div>

      <div className="card flex flex-col gap-4 p-6">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-accent text-accent-ink">
          <StoreIcon />
        </span>
        <h3 className="text-[22px] font-semibold tracking-[-0.01em]">If you&apos;re selling</h3>
        <p className="text-[16px] text-ink-2">
          List what you&apos;ve got and your floor price. Your agent bids for you in sealed rounds, never below
          your floor, and comes back with a reason every time it loses, not just a rejection.
        </p>
        <ul className="grid gap-2 text-[15px] text-ink-2">
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>One flat fee for everyone: no pay-for-rank, no hidden boost.</li>
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>A loss report every round: the gap, the reason, and the source.</li>
          <li className="flex gap-2"><span className="text-mint" aria-hidden>✓</span>Your agent learns: price step, bundle, delivery promise, inside your own rules.</li>
        </ul>
        <Link href="/sell" className="btn mt-auto inline-flex min-h-12 w-fit items-center gap-2 rounded-full border-2 border-line-2 bg-panel px-6 text-[15px] font-semibold text-ink hover:bg-soft">
          List your shop <span aria-hidden>→</span>
        </Link>
      </div>
    </section>
  );
}
