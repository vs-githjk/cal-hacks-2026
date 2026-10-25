"use client";
// Buyer sign-up: a name (and optional phone) creates the account, then the visitor lands on /buyer.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useReducer, useSpacetimeDB, useTable } from "spacetimedb/react";
import { reducers, tables } from "@/module_bindings";
import { cleanSignUp, gateRoute, signUpErrorText } from "@/lib/signUp";

const field = "w-full min-h-11 rounded-lg border border-line bg-soft px-3 py-2";

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
    <section className="card mx-auto w-full max-w-md p-6">
      <h1 className="mb-4 text-lg font-semibold">Start as a buyer</h1>
      {route === "connecting" ? (
        <p className="text-sm text-muted">Connecting to the market...</p>
      ) : route === "buyer" ? (
        <div className="grid gap-3">
          <p className="text-sm text-muted">This browser already has an account.</p>
          <Link href="/buyer" className="inline-flex min-h-11 items-center justify-center rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink">
            Continue as {shown}
          </Link>
        </div>
      ) : (
        <form className="grid gap-4" onSubmit={onSubmit}>
          <label className="grid gap-1 text-sm">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={40} autoComplete="name" className={field} />
          </label>
          <label className="grid gap-1 text-sm">
            Phone (optional, only for the approval call)
            <input value={phone} onChange={(e) => setPhone(e.target.value)} type="tel" autoComplete="tel" className={field} />
          </label>
          <p className="text-sm text-muted">We never see your card. Payments tonight are sandbox.</p>
          {error && <p role="alert" className="text-sm text-coral">{error}</p>}
          <button disabled={submitting} className="min-h-11 w-full rounded-lg bg-accent px-4 py-2 font-medium text-accent-ink disabled:opacity-60">
            Create my account
          </button>
        </form>
      )}
      <Link href="/buyer?pair=1" className="mt-4 inline-flex min-h-11 items-center text-sm text-muted underline">
        Have a pairing code from the operator?
      </Link>
    </section>
  );
}
