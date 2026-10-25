import { BRAND } from "@/lib/brand";

// Shown by the service worker when a page cannot be reached. Static on purpose: no market data, so no numbers.

export default function OfflinePage() {
  return (
    <section className="card mx-auto max-w-md p-6">
      <h1 className="mb-2 text-lg font-semibold">You are offline</h1>
      <p className="text-sm text-muted">
        {BRAND} cannot reach the market from here. Nothing is shown from memory, so no goal, price or approval appears on this page. Reconnect and open the app again.
      </p>
    </section>
  );
}
