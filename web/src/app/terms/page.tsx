import type { Metadata } from "next";
import { BRAND } from "@/lib/brand";

export const metadata: Metadata = { title: "Terms" };

/** The terms of a sandbox: what this is, what it is not, and the license. */
export default function TermsPage() {
  return (
    <article className="mx-auto grid max-w-2xl gap-5 px-4 py-10 text-[15px] leading-6 text-ink-2">
      <h1 className="text-[28px] font-semibold leading-[34px] tracking-[-0.02em] text-ink">Terms</h1>
      <p>{BRAND} is a demonstration built for a hackathon. It runs in sandbox mode only: test identities, Stripe test cards, and no real purchases. Nothing on this site is an offer to sell goods.</p>
      <p><b className="text-ink">No advice.</b> Prices shown come from dated store listings or simulated sellers, each labelled. They are not quotes.</p>
      <p><b className="text-ink">Your approval.</b> A purchase above your allowance is paid only after you say the one-time code on the phone call. A wrong code, silence or a hang-up pays nothing.</p>
      <p><b className="text-ink">Sellers.</b> A seller agent bids within its owner&apos;s listings and never below its floor. Sellers see a band of a buyer&apos;s budget, not the exact cap.</p>
      <p><b className="text-ink">License.</b> The software is released under the MIT License. Copyright (c) 2026 the {BRAND} team.</p>
    </article>
  );
}
