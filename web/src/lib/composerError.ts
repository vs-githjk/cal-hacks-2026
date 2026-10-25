// #449 PL-13: the composer's error line. A reducer refusal carries buyer ids, goal ids and function names, so a customer reads a plain sentence instead.

export const POST_GOAL_FALLBACK = "The request could not be sent. Try again in a moment.";

/** A plain sentence for whatever post_goal threw; the raw message is never returned. */
export function postGoalErrorText(err: unknown): string {
  const m = err instanceof Error ? err.message : "";
  if (/not allowed|acts only for|no role|not a buyer/i.test(m)) return "This screen is not signed in as a buyer. Refresh the page and sign in again.";
  if (/already exists/i.test(m)) return "That request was already sent. It is under Active searches.";
  if (/cap must/i.test(m)) return "Add a top price above zero.";
  if (/deadline/i.test(m)) return "Pick the date you need it by.";
  if (/quantity/i.test(m)) return "Ask for at least one.";
  if (/websocket|network|connect|timed? ?out|fetch|offline/i.test(m)) return "The market is not reachable right now. Check your connection and try again.";
  return POST_GOAL_FALLBACK;
}
