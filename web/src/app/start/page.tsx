"use client";
// Buyer sign-up: a name (and optional phone) creates the account, then the visitor lands on /buyer.
// Design system v2 (#430): one glass card holds the form; on a phone it is the first thing on screen, with inputs at 17 px so iOS never zooms.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { cleanSignUp, gateRoute, signUpErrorText } from "@/lib/signUp";
import { BRAND, SHIELD } from "@/lib/brand";
import { BrandMark } from "@/components/BrandMark";

const field =
  "w-full min-h-12 rounded-xl border-0 bg-surface px-4 text-[17px] text-ink shadow-ring outline-none transition-shadow placeholder:text-muted/70 focus:shadow-[var(--shadow-ring),var(--shadow-focus)]";

const STEPS: { title: string; text: string }[] = [
  { title: "Create your account", text: "A name, and a phone number if you want the approval call." },
  { title: "Tell it the part you need", text: "A part, a price cap and a date. Seller agents bid in a sealed round." },
  { title: "Approve by phone", text: "Above your allowance it calls you. Only the code on your screen plus \"approve\" pays." },
];

export default function StartPage() {
  const router = useRouter();
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  const [profiles] = useTable(tables.myBuyerProfile);
  const signUp = useReducer(reducers.signUpBuyer);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const route = gateRoute(conn.isActive, rolesReady, roles, false);

  useEffect(() => {
    if (route === "buyer" && submitted) router.replace("/buyer");
  }, [route, submitted, router]);

  const buyerId = roles.find((r) => r.role === "buyer")?.subjectId ?? "";
  const shown = profiles[0]?.displayName || buyerId;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const clean = cleanSignUp(name, phone);
    if ("error" in clean) return setError(clean.error);
    setSubmitting(true);
    try {
      await signUp({ displayName: clean.displayName, phone: clean.phone });
      setSubmitted(true);
    } catch (err) {
      setError(signUpErrorText(err instanceof Error ? err.message : ""));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-[1120px] items-start gap-8 pt-2 md:grid-cols-[1fr_440px] md:gap-16 md:px-4 md:pt-12">
      <div className="grid gap-4 md:gap-6 md:pt-6">
        <span className="inline-flex w-max items-center gap-2 text-[15px] font-medium text-ink-2">
          <span className="dot text-live" aria-hidden /> Sandbox. Test-mode money, no card needed.
        </span>
        <h1 className="text-[34px] font-medium leading-[38px] tracking-[-0.025em] text-balance md:text-[56px] md:leading-[60px]">
          Your agent shops. <span className="text-muted">You approve.</span>
        </h1>
        <p className="max-w-[44ch] text-[17px] leading-[26px] text-ink-2 max-md:hidden">
          Start a buyer account on {BRAND}. Seller agents compete for your PC parts, {SHIELD} screens every listing, and nothing above your allowance is paid until you say the code on the phone.
        </p>
        <ol className="mt-2 grid gap-0 max-md:hidden">
          {STEPS.map((s, i) => (
            <li key={s.title} className="grid grid-cols-[32px_1fr] gap-4 border-t border-line py-4 first:border-t-0">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-surface font-mono text-[13px] font-medium text-ink shadow-ring">{i + 1}</span>
              <span>
                <span className="block text-[17px] font-semibold leading-[22px]">{s.title}</span>
                <span className="mt-1 block text-[15px] leading-5 text-muted">{s.text}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      <section className="glass grid gap-5 p-5 md:p-8" aria-labelledby="start-title">
        <div className="flex items-center justify-between gap-3">
          <h2 id="start-title" className="text-[22px] font-semibold leading-7 tracking-[-0.01em]">Start as a buyer</h2>
          <BrandMark size={28} />
        </div>

        {route === "connecting" ? (
          <div className="grid gap-3" aria-busy>
            <div className="h-12 rounded-xl bg-surface-2 motion-safe:animate-pulse" />
            <div className="h-12 rounded-xl bg-surface-2 motion-safe:animate-pulse" />
            <p className="text-[13px] leading-[18px] text-muted">Connecting to the market. The form opens when it answers.</p>
          </div>
        ) : route === "buyer" ? (
          <div className="grid gap-4">
            {submitted ? (
              <p className="flex items-center gap-3 text-[15px] text-ink-2">
                <span className="grid h-7 w-7 place-items-center rounded-full bg-mint-soft text-mint motion-safe:animate-[pop_420ms_var(--ease-out)_both]" aria-hidden>✓</span>
                Account created. Opening your dashboard.
              </p>
            ) : (
              <p className="text-[15px] leading-5 text-ink-2">This browser already has a buyer account.</p>
            )}
            <Link href="/buyer" className="btn inline-flex min-h-12 items-center justify-center rounded-xl bg-pulse px-5 text-[17px] font-medium text-pulse-ink hover:shadow-card">
              Continue as {shown}
            </Link>
          </div>
        ) : (
          <form className="grid gap-4" onSubmit={onSubmit} noValidate>
            <label className="grid gap-1.5">
              <span className="text-[13px] font-medium leading-[18px] text-ink-2">Your name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={40} autoComplete="name" enterKeyHint="next" placeholder="First name is fine" className={field} />
            </label>
            <label className="grid gap-1.5">
              <span className="flex items-baseline justify-between gap-2 text-[13px] font-medium leading-[18px] text-ink-2">
                Phone for the approval call <span className="font-normal text-muted">optional</span>
              </span>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" inputMode="tel" autoComplete="tel" enterKeyHint="go" placeholder="+1 415 555 0100" className={`${field} font-mono`} />
              <span className="text-[13px] leading-[18px] text-muted">Only used when a buy is above your allowance. It rings, reads the deal, and waits for the code on your screen.</span>
            </label>
            {error && (
              <p role="alert" className="flex items-start gap-2 text-[13px] leading-[18px] text-ink-2">
                <span className="inline-flex h-6 shrink-0 items-center rounded-full bg-coral-soft px-2.5 text-[12px] font-medium text-coral">Error</span>
                {error}
              </p>
            )}
            <button disabled={submitting} className="btn mt-1 min-h-12 w-full rounded-xl bg-pulse px-5 text-[17px] font-medium text-pulse-ink hover:shadow-card disabled:opacity-60">
              {submitting ? "Creating your account..." : "Create my account"}
            </button>
            <p className="flex items-center gap-2 text-[13px] leading-[18px] text-muted">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
              We never see your card. Payments are Stripe test mode.
            </p>
          </form>
        )}

        <div className="border-t border-line pt-4">
          <Link href="/buyer?pair=1" className="inline-flex min-h-11 items-center gap-1.5 text-[15px] font-medium text-pulse">
            Have a pairing code from the operator? <span aria-hidden>→</span>
          </Link>
        </div>
      </section>

      <ol className="grid gap-3 md:hidden">
        {STEPS.map((s, i) => (
          <li key={s.title} className="card grid grid-cols-[28px_1fr] gap-3 p-4">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-surface-2 font-mono text-[12px] font-medium">{i + 1}</span>
            <span>
              <span className="block text-[15px] font-semibold leading-5">{s.title}</span>
              <span className="mt-0.5 block text-[13px] leading-[18px] text-muted">{s.text}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
