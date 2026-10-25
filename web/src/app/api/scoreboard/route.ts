// Serves the scoreboard (contracts/Scoreboard.schema.json) from a copy bundled with the web build: the repo's
// data/ folder is not part of the hosted deploy, so reading ../data/scoreboard.json 404ed there.
import scoreboard from "@/lib/fixtures/scoreboard.json";

export async function GET() {
  return Response.json(scoreboard);
}
