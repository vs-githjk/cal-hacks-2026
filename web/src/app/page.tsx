import Link from "next/link";

export default function Home() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Tech Bazaar</h1>
      <p className="max-w-2xl text-[var(--muted)]">
        A buyer&apos;s agent for scarce, scam-prone computer gear. Seller agents bid in a sealed round, the advocate
        vetoes traps with a source, and nothing is paid until the buyer approves.
      </p>
      <div className="flex gap-3">
        <Link href="/buyer" className="panel px-4 py-3 font-medium hover:border-[var(--accent)]">
          Buyer screen
        </Link>
        <Link href="/market" className="panel px-4 py-3 font-medium hover:border-[var(--accent)]">
          Market state
        </Link>
      </div>
    </div>
  );
}
