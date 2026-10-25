import type { Metadata } from "next";
import { BRAND, SHIELD } from "@/lib/brand";

export const metadata: Metadata = { title: "Privacy" };

/** What this sandbox stores and why. Plain facts; no legal boilerplate beyond what is true. */
export default function PrivacyPage() {
  return (
    <article className="mx-auto grid max-w-2xl gap-5 px-4 py-10 text-[15px] leading-6 text-ink-2">
      <h1 className="text-[28px] font-semibold leading-[34px] tracking-[-0.02em] text-ink">Privacy</h1>
      <p>{BRAND} is a hackathon project running in sandbox mode. There is no real money, no real card and no production account.</p>
      <p><b className="text-ink">What we store.</b> The name and phone number you give at sign-up, the goals you post, and the market rows those goals create: bids, checks, approvals and test-mode receipts. They live in the market database (SpacetimeDB) under your buyer id.</p>
      <p><b className="text-ink">Why the phone.</b> A purchase above your allowance is approved by a call to that number. The number is used for that call and for nothing else.</p>
      <p><b className="text-ink">What we never do.</b> We do not sell or share your data, we never ask for a card, and the {SHIELD} screens seller messages before any agent acts on them.</p>
      <p><b className="text-ink">Labels.</b> Every number on screen carries LIVE, MIRROR or SIM so you can see what was real, mirrored from a dated listing, or simulated.</p>
      <p><b className="text-ink">Removal.</b> Ask the operator and your buyer row and its goals are deleted.</p>
    </article>
  );
}
