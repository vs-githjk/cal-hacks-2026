"use client";
// Buyer sign-up: a name and a phone (required, #449 PL-15: purchases are approved by a call to it) create the account, then the visitor lands on /buyer.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { cleanSignUp, continueLabel, gateRoute, pairCodeToSend, signUpErrorText } from "@/lib/signUp";
import { Tag } from "@/components/ui";

// Operator pairing: the same demo buyer BuyerGate pairs as (SIM sign-in).
const DEMO_BUYER = "vidyut";

const field = "w-full min-h-11 rounded-xl bg-surface px-4 text-[15px]/[20px] text-ink shadow-ring focus:shadow-[var(--shadow-ring),var(--shadow-focus)] focus:outline-none";
const primary = "btn inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-pulse px-5 font-medium text-pulse-ink disabled:opacity-60";

export default function StartPage() {
  const router = useRouter();
  const conn = useSpacetimeDB();
  const [roles, rolesReady] = useTable(tables.myRole);
  const [profiles] = useTable(tables.myBuyerProfile);
  const signUp = useReducer(reducers.signUpBuyer);
  const pair = useReducer(reducers.pairBuyerScreen);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const route = gateRoute(conn.isActive, rolesReady, roles, false);

  useEffect(() => {
    if (route === "buyer" && submitted) router.replace("/buyer");
  }, [route, submitted, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const toPair = pairCodeToSend(code);
    if (toPair) {
      setSubmitting(true);
      try {
        await pair({ buyerId: DEMO_BUYER, code: toPair });
        setSubmitted(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "That code did not match.");
      } finally {
        setSubmitting(false);
      }
      return;
    }
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
    <section className="card mx-auto grid w-full max-w-md gap-4 p-4 md:p-6">
      <h1 className="text-[22px]/[28px] font-semibold tracking-[-0.01em]">Start as a buyer</h1>
      {route === "connecting" ? (
        <p className="text-[15px]/[20px] text-muted">Connecting to the market...</p>
      ) : route === "buyer" ? (
        <div className="grid gap-3">
          <p className="text-[15px]/[20px] text-muted">This browser already has an account.</p>
          <Link href="/buyer" className={primary}>
            {continueLabel(profiles[0]?.displayName)}
          </Link>
        </div>
      ) : (
        <form className="grid gap-4" onSubmit={onSubmit} noValidate>
          <label className="grid gap-1.5 text-[13px]/[18px] font-medium text-ink-2">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required={!code} maxLength={40} autoComplete="name" className={`${field} text-[17px]`} />
          </label>
          <label className="grid gap-1.5 text-[13px]/[18px] font-medium text-ink-2">
            Phone
            <input value={phone} onChange={(e) => setPhone(e.target.value)} required={!code} type="tel" inputMode="tel" autoComplete="tel" placeholder="+1 415 555 0100" className={`${field} text-[17px]`} />
            <span className="font-normal text-muted">We call you to approve purchases above your allowance.</span>
          </label>
          <label className="grid gap-1.5 text-[13px]/[18px] font-medium text-ink-2">
            <span className="flex justify-between">Pairing code <span className="font-normal text-muted">optional</span></span>
            <input value={code} onChange={(e) => setCode(e.target.value)} autoCapitalize="characters" autoCorrect="off" spellCheck={false} autoComplete="off" placeholder="From the operator" className={`${field} font-mono text-[17px]`} />
          </label>
          {error && <p role="alert" className="text-[13px]/[18px] text-coral">{error}</p>}
          <button disabled={submitting} className={primary}>
            {code.trim() ? "Pair this screen" : "Create my account"}
          </button>
          <p className="flex items-center gap-2 text-[13px]/[18px] text-muted"><Tag>Test mode</Tag> No card, no real money.</p>
        </form>
      )}
    </section>
  );
}
