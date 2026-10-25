"use client";
// A 2 px bar under the header that fills as the page scrolls (#448, Vidyut). Cyan into koi. Decorative; hidden from readers.
import { useEffect, useState } from "react";

export function ScrollProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const on = () => {
      const max = document.documentElement.scrollHeight - innerHeight;
      setP(max > 0 ? Math.min(1, scrollY / max) : 0);
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
