const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

export function isLocalHost(host: string): boolean {
  const h = host.toLowerCase();
  return LOCAL_HOSTS.has(h) || h.endsWith(".localhost");
}

function uriHost(uri: string): string {
  const rest = uri.replace(/^(wss?|https?):\/\//i, "");
  const authority = rest.split(/[/?#]/)[0];
  if (authority.startsWith("[")) return authority.slice(0, authority.indexOf("]") + 1);
  return authority.split(":")[0];
}

/** The SpacetimeDB URI to connect to, or null when the page must not connect: unset on a deployed host, or a loopback URI seen from a deployed host. Mirrors feedBase in agentFeed.ts. */
export function stdbUri(env: string | undefined, pageHost: string): string | null {
  const local = isLocalHost(pageHost);
  if (!env) return local ? "ws://127.0.0.1:3000" : null;
  if (!local && isLocalHost(uriHost(env))) return null;
  return env;
}
