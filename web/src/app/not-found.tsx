import Link from "next/link";
import { Card } from "@/components/ui";

const WAYS: { href: string; label: string; text: string }[] = [
  { href: "/", label: "Home", text: "What Tech Bazaar is, and the market right now." },
  { href: "/start", label: "Start as a buyer", text: "Set a goal and let your agent shop for it." },
  { href: "/market", label: "Market", text: "The referee's floor: the sealed round and every bid." },
];

/** Any address the app does not have (#398): say so plainly and offer the way back, never a bare 404. */
export default function NotFound() {
  return (
    <div className="mx-auto grid max-w-2xl gap-4 px-4 py-10">
      <h1 className="text-[22px] font-semibold">There is no page at this address.</h1>
      <p className="text-muted">The link may be old. These are the places a buyer usually goes next:</p>
      <div className="grid gap-3">
        {WAYS.map((w) => (
          <Link key={w.href} href={w.href} className="block">
            <Card tactile>
              <p className="font-medium">{w.label}</p>
              <p className="mt-1 text-[14px] text-muted">{w.text}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
