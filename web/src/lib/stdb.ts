import { DbConnection } from "@/module_bindings";
import type { Timestamp } from "spacetimedb";
import { stdbUri } from "./stdbUri.ts";

export { stdbUri, isLocalHost } from "./stdbUri.ts";

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

/** Stands in for the builder when this host must not connect: it never opens a socket, so isActive stays false. */
function inertBuilder(): ReturnType<typeof realBuilder> {
  const connection = {
    isActive: false,
    identity: undefined,
    token: undefined,
    connectionId: { toHexString: () => "0" },
    isDisconnectRequested: true,
    removeOnConnect() {},
    removeOnAutomaticReconnect() {},
    removeOnDisconnect() {},
    removeOnConnectError() {},
    disconnect() {},
  };
  const builder: Record<string, unknown> = {
    getUri: () => "inert://no-database",
    getModuleName: () => STDB_DB,
    build: () => connection,
  };
  for (const name of ["withAutomaticReconnect", "withToken", "onConnect", "onAutomaticReconnect", "onDisconnect", "onConnectError"]) {
    builder[name] = () => builder;
  }
  return builder as unknown as ReturnType<typeof realBuilder>;
}

function realBuilder(uri: string) {
  return DbConnection.builder()
    .withUri(uri)
    .withDatabaseName(STDB_DB)
    .withToken(readToken())
    .onConnect((_conn, _identity, token) => saveToken(token));
}

export function connectionBuilder() {
  const uri = typeof window === "undefined" ? null : stdbUri(process.env.NEXT_PUBLIC_SPACETIMEDB_URI, window.location.hostname);
  if (uri === null) {
    console.info("[stdb] no database for this host");
    return inertBuilder();
  }
  return realBuilder(uri);
}

export const toDate = (ts: Timestamp) => new Date(Number(ts.microsSinceUnixEpoch / BigInt(1000)));

export { formatMoney as fmtMoney } from "./money";

export const fmtTime = (ts: Timestamp) => toDate(ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
