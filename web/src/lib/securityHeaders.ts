// The security headers for web/next.config.ts (#449 PL-23). Pure, so node --test can check them.
//
// What the app really loads: its own scripts and styles, fonts self-hosted by next/font, avatar images from whatever
// https host the agent feed names, a WebSocket to SpacetimeDB (NEXT_PUBLIC_SPACETIMEDB_URI) and fetches to the local
// services (feed, Seller Kit, Hyphenate). 'unsafe-inline' stays on scripts and styles because Next writes inline
// scripts (the RSC payload) and React writes style attributes; a per-request nonce would need dynamic rendering, which
// the static shell here avoids. 'unsafe-eval' is on scripts because the SpacetimeDB SDK builds its row deserializers
// with new Function (seen as an EvalError in the browser: without it no page loads). So script-src is weak by necessity;
// the rest of the policy still stops framing, plugins, base-tag and form hijacks and any connection to an origin the app does not name.

type Env = Readonly<Record<string, string | undefined>>;

const DEFAULTS = {
  NEXT_PUBLIC_SPACETIMEDB_URI: "ws://127.0.0.1:3000",
  NEXT_PUBLIC_AGENT_FEED_URL: "http://127.0.0.1:8790",
  NEXT_PUBLIC_SELLER_KIT_URL: "http://127.0.0.1:8791",
  NEXT_PUBLIC_HYPHENATE_URL: "http://127.0.0.1:8789",
};
const SCHEMES = new Set(["ws:", "wss:", "http:", "https:"]);

/** The origins one URL setting needs: a ws(s) URL needs its http(s) twin too (the SDK also makes plain requests). */
function originsOf(raw: string | undefined): string[] {
  let u: URL;
  try {
    u = new URL((raw ?? "").trim());
  } catch {
    return [];
  }
  if (!SCHEMES.has(u.protocol) || !u.host) return [];
  const secure = u.protocol === "wss:" || u.protocol === "https:";
  const ws = `${secure ? "wss" : "ws"}://${u.host}`;
  const http = `${secure ? "https" : "http"}://${u.host}`;
  return u.protocol.startsWith("ws") ? [ws, http] : [http];
}

export function buildCsp(env: Env, dev: boolean): string {
  const connect = new Set<string>(["'self'"]);
  // The same rule the app uses (a setting that is empty or unset means its default); a set but unusable value adds nothing.
  for (const [name, fallback] of Object.entries(DEFAULTS)) for (const o of originsOf(env[name] || fallback)) connect.add(o);
  if (dev) for (const o of ["ws://localhost:*", "ws://127.0.0.1:*"]) connect.add(o);   // next dev hot reload
  const directives: [string, string[]][] = [
    ["default-src", ["'self'"]],
    ["script-src", ["'self'", "'unsafe-inline'", "'unsafe-eval'"]],
    ["style-src", ["'self'", "'unsafe-inline'"]],
    ["img-src", ["'self'", "data:", "blob:", "https:"]],
    ["font-src", ["'self'", "data:"]],
    ["connect-src", [...connect]],
    ["worker-src", ["'self'"]],
    ["manifest-src", ["'self'"]],
    ["object-src", ["'none'"]],
    ["base-uri", ["'self'"]],
    ["form-action", ["'self'"]],
    ["frame-ancestors", ["'none'"]],
  ];
  return directives.map(([name, values]) => `${name} ${values.join(" ")}`).join("; ");
}

export function securityHeaders(env: Env, dev: boolean): { key: string; value: string }[] {
  return [
    { key: "Content-Security-Policy", value: buildCsp(env, dev) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
    ...(dev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=31536000" }]),
  ];
}
