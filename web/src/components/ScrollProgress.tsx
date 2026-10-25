"use client";
// A 2 px bar under the header that fills as the page scrolls (#448, Vidyut). Cyan into koi. Decorative; hidden from readers.
// It also drives the water: the aquarium and the primary buttons share one gradient (--fm-g1, --fm-g2) that shifts from
// blue-to-cyan at the top of the page to indigo-to-teal over the first screen and a half of scrolling.
import { useEffect, useState } from "react";

export function ScrollProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const mix = (a: string, b: string, t: number) => {
      const c = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
      const [x, y] = [c(a), c(b)];
      return `rgb(${x.map((v, i) => Math.round(v + (y[i]! - v) * t)).join(",")})`;
    };
    const on = () => {
      const max = document.documentElement.scrollHeight - innerHeight;
      setP(max > 0 ? Math.min(1, scrollY / max) : 0);
      const t = Math.min(1, scrollY / (innerHeight * 1.5));
      const root = document.documentElement.style;
      root.setProperty("--fm-g1", mix("#1e4ed8", "#4f46e5", t));
      root.setProperty("--fm-g2", mix("#0891b2", "#14b8a6", t));
    };
    on();
    addEventListener("scroll", on, { passive: true });
    addEventListener("resize", on);
    return () => {
      removeEventListener("scroll", on);
      removeEventListener("resize", on);
    };
  }, []);
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[60px] z-40 h-0.5 md:top-[60px]" aria-hidden>
      <div className="h-full origin-left bg-[linear-gradient(90deg,var(--color-live),var(--color-koi))] transition-transform duration-150 ease-out" style={{ transform: `scaleX(${p})` }} />
    </div>
  );
}
