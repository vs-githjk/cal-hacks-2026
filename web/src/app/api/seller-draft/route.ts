// #484: POST { text } -> a vetted draft of a seller config, or { ok: false, note } when Claude cannot be used.
// The key is read here, on the server, and goes only to api.anthropic.com. All the rules live in lib/sellerDraft.ts.
import { RATE_NOTE, allowDraft, handleDraftRequest } from "@/lib/sellerDraft";

const SEEN = new Map<string, number[]>(); // #484: per-instance rate limit, see allowDraft

export const maxDuration = 15;

export async function POST(req: Request): Promise<Response> {
  const caller = (req.headers.get("x-forwarded-for") ?? "").split(",")[0]!.trim() || "unknown";
  if (!allowDraft(caller, Date.now(), SEEN)) {
    return Response.json({ ok: false, note: RATE_NOTE }, { status: 429, headers: { "cache-control": "no-store" } });
  }
  let body: unknown = null;
  try {
    body = await req.json();
  } catch {
    /* not JSON: handleDraftRequest answers 400 */
  }
  const { status, body: out } = await handleDraftRequest(body, { apiKey: process.env.ANTHROPIC_API_KEY });
  return Response.json(out, { status, headers: { "cache-control": "no-store" } });
}
