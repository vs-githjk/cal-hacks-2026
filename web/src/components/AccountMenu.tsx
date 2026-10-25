"use client";
// Header account control: the signed-in name with a dot, a small menu, and a warned sign-out.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { signOut } from "@/lib/stdb";

const item = "flex min-h-10 w-full items-center px-3 text-left text-[14px] text-ink hover:bg-ink/5";

/** Renders nothing until this browser has a buyer role, so the caller can show its sign-in CTA instead. */
export function AccountMenu({ fallback }: { fallback?: React.ReactNode }) {
  const [roles] = useTable(tables.myRole);
  const [profiles] = useTable(tables.myBuyerProfile);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = () => { setOpen(false); setConfirming(false); };
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const buyerId = roles.find((r) => r.role === "buyer")?.subjectId;
  if (!buyerId) return <>{fallback}</>;
  const name = profiles.find((p) => p.buyerId === buyerId)?.displayName || profiles[0]?.displayName || "Your account";
  const shut = () => { setOpen(false); setConfirming(false); };

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => { setOpen(!open); setConfirming(false); }}
        className="inline-flex min-h-10 max-w-[180px] items-center gap-2 rounded-xl px-3 text-[14px] font-medium text-ink hover:bg-ink/5"
      >
        <span className="h-2 w-2 shrink-0 rounded-full bg-live" aria-hidden />
        <span className="truncate">{name}</span>
      </button>
      {open && (
        <div role="menu" aria-label="Account" className="absolute right-0 top-full z-50 mt-1 w-64 border border-line bg-surface py-1">
          {confirming ? (
            <div className="p-3">
              <p className="text-[14px]/[20px] text-ink">
                Sign out of this browser? Your account lives only in this browser. After signing out you cannot get back into it.
              </p>
              <div className="mt-3 flex gap-2">
                <button type="button" autoFocus onClick={signOut} className="min-h-10 flex-1 border border-ink px-3 text-[14px] font-medium text-ink hover:bg-ink/5">Sign out</button>
                <button type="button" onClick={() => setConfirming(false)} className="min-h-10 flex-1 px-3 text-[14px] text-ink-2 hover:bg-ink/5">Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <Link role="menuitem" href="/buyer" onClick={shut} className={item}>Your dashboard</Link>
              <Link role="menuitem" href="/buyer#new-search" onClick={shut} className={item}>Your searches</Link>
              <button type="button" role="menuitem" onClick={() => setConfirming(true)} className={item}>Sign out</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
