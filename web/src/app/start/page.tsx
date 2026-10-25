"use client";
// Buyer sign-up: a name and a phone (required: purchases are approved by a call) create the account, then the visitor lands on /buyer.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { cleanSignUp, continueLabel, gateRoute, signUpErrorText } from "@/lib/signUp";

const field = "w-full min-h-11 rounded-xl bg-surface px-4 text-[15px]/[20px] text-ink shadow-ring focus:shadow-[var(--shadow-ring),var(--shadow-focus)] focus:outline-none";
const primary = "btn inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-pulse px-5 font-medium text-pulse-ink disabled:opacity-60";

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
        <form className="grid gap-4" onSubmit={onSubmit}>
          <label className="grid gap-1.5 text-[13px]/[18px] font-medium text-ink-2">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={40} autoComplete="name" className={field} />
          </label>
          <label className="grid gap-1.5 text-[13px]/[18px] font-medium text-ink-2">
            Phone (we call this number to approve a purchase)
            <input value={phone} onChange={(e) => setPhone(e.target.value)} required type="tel" autoComplete="tel" placeholder="+1 415 555 0100" className={field} />
          </label>
          <p className="rounded-xl bg-surface-2 px-4 py-3 text-[13px]/[18px] text-ink-2">We never see your card. Payments tonight are sandbox.</p>
          {error && <p role="alert" className="text-[13px]/[18px] text-coral">{error}</p>}
          <button disabled={submitting} className={primary}>
            Create my account
          </button>
        </form>
      )}
      <Link href="/buyer?pair=1" className="inline-flex min-h-11 items-center text-[13px]/[18px] text-muted underline underline-offset-2">
        Have a pairing code from the operator?
      </Link>
    </section>
  );
}
