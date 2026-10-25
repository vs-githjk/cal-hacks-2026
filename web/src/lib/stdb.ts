import { DbConnection } from "@/module_bindings";
import type { Timestamp } from "spacetimedb";
import { isTokenRejected } from "./signUp";

export const STDB_URI = process.env.NEXT_PUBLIC_SPACETIMEDB_URI || "ws://127.0.0.1:3000";
export const STDB_DB = process.env.NEXT_PUBLIC_SPACETIMEDB_DB || "tech-bazaar";
export const TOKEN_KEY = `tb_token_${STDB_DB}`;

function readToken(): string | undefined {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

function saveToken(token: string) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Private window or blocked storage: the screen still works, with a fresh identity per load.
  }
}

export function connectionBuilder() {
  const stored = readToken();
  return DbConnection.builder()
    .withUri(STDB_URI)
    .withDatabaseName(STDB_DB)
    .withToken(stored)
    .onConnect((_conn, _identity, token) => saveToken(token))
    // Only an explicit token refusal clears it (then one reload with a fresh identity); flaky data keeps the account.
    .onConnectError((_ctx, err) => {
      if (stored && isTokenRejected(err)) {
        try {
          localStorage.removeItem(TOKEN_KEY);
        } catch {
          return;
        }
        location.reload();
      }
    });
}

export const toDate = (ts: Timestamp) => new Date(Number(ts.microsSinceUnixEpoch / BigInt(1000)));

export { formatMoney as fmtMoney } from "./money";

export const fmtTime = (ts: Timestamp) => toDate(ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });

/** Forget this browser's account (its stored token) and return to the landing page, which starts a fresh identity. */
export function signOut() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Blocked storage: nothing was stored, so the redirect alone is enough.
  }
  // A full page load on purpose: it drops the live connection that still holds the old identity.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/");
}
