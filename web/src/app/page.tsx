import Link from "next/link";
import { DotPattern } from "@/components/ui/dot-pattern";

export default function Home() {
  return (
    <div className="grid gap-6">
      <section className="relative -mx-4 overflow-hidden px-4 pb-10 pt-12 sm:pb-14 sm:pt-16">
        {/* Decorative dot field behind the headline only; the wide radial mask fades it out before any small text. */}
        <DotPattern width={18} height={18} cx={1.4} cy={1.4} cr={1.4} className="fill-muted/30 [mask-image:radial-gradient(ellipse_70%_60%_at_40%_45%,white,transparent)]" />
        <h1 className="relative z-10 max-w-3xl font-display text-[clamp(36px,5.5vw,64px)] leading-[1.05] tracking-[-0.01em] text-balance">
          An agent that buys computer gear for you.
        </h1>
      </section>
      <p className="max-w-2xl text-muted">
        Sellers bid in a sealed round, your agent vetoes traps with proof, and it calls you before spending more than you allowed.
      </p>
      <div className="flex flex-wrap gap-3">
        <Link href="/buyer" className="card px-4 py-3 font-medium motion-safe:transition-transform motion-safe:duration-150 motion-safe:hover:-translate-y-0.5 hover:border-accent">
          Buyer screen
        </Link>
        <Link href="/market" className="card px-4 py-3 font-medium motion-safe:transition-transform motion-safe:duration-150 motion-safe:hover:-translate-y-0.5 hover:border-accent">
          Market state
        </Link>
        <Link href="/floor" className="card px-4 py-3 font-medium motion-safe:transition-transform motion-safe:duration-150 motion-safe:hover:-translate-y-0.5 hover:border-accent">
          3D floor
        </Link>
      </div>
    </div>
  );
}
