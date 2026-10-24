import { DbConnection } from "@/module_bindings";
import type { Timestamp } from "spacetimedb";

export const STDB_URI = process.env.NEXT_PUBLIC_SPACETIMEDB_URI || "ws://127.0.0.1:3000";
export const STDB_DB = process.env.NEXT_PUBLIC_SPACETIMEDB_DB || "tech-bazaar";
const TOKEN_KEY = `tb_token_${STDB_DB}`;

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
  return DbConnection.builder()
    .withUri(STDB_URI)
    .withDatabaseName(STDB_DB)
    .withToken(readToken())
    .onConnect((_conn, _identity, token) => saveToken(token));
}

export const toDate = (ts: Timestamp) => new Date(Number(ts.microsSinceUnixEpoch / BigInt(1000)));

export { formatMoney as fmtMoney } from "./money";

export const fmtTime = (ts: Timestamp) => toDate(ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
