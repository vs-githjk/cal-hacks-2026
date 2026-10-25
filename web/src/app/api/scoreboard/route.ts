// Serves Lane C's data/scoreboard.json (contracts/Scoreboard.schema.json) as is, read on each request so a rerun shows.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { connection } from "next/server";

export async function GET() {
  await connection();
  try {
    const text = await readFile(path.join(process.cwd(), "..", "data", "scoreboard.json"), "utf8");
    return new Response(text, { headers: { "content-type": "application/json" } });
  } catch {
    return Response.json({ tiles: [] }, { status: 404 });
  }
}
