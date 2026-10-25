"use client";
// Registers the service worker (production only, so dev hot reload is never served from a cache) and shows the number of
// approvals waiting for this paired screen on the installed app's icon. Where the Badging API or a service worker is not
// supported nothing happens and nothing is shown. No web push.

import { useEffect } from "react";
import { useTable } from "spacetimedb/react";
import { tables } from "@/module_bindings";
import { badgeAction } from "@/lib/pwa";

type Badging = { setAppBadge?: (n: number) => Promise<void>; clearAppBadge?: () => Promise<void> };

export function PwaRegister() {
  const [pending] = useTable(tables.myPendingApprovals);
  const count = pending.length;

  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // an unsupported or blocked worker only means no offline page
      });
    }
  }, []);

  useEffect(() => {
    const nav = navigator as Navigator & Badging;
    const act = badgeAction(count);
    const done = act.kind === "set" ? nav.setAppBadge?.(act.count) : nav.clearAppBadge?.();
    done?.catch(() => {
      // a refused badge is silent
    });
  }, [count]);

  return null;
}
