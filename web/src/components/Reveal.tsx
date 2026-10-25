"use client";
// Reveal on scroll (#448, round 10): a section fades and rises 14 px once, when it enters the viewport. Static under reduced motion.
import { useEffect, useRef, type ReactNode } from "react";

export function Reveal({ children, className = "", as: Tag = "div" }: { children: ReactNode; className?: string; as?: "div" | "section" }) {
  const ref = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { el.classList.add("is-in"); return; }
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { el.classList.add("is-in"); io.disconnect(); }
    }, { rootMargin: "0px 0px -10% 0px", threshold: 0.08 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return <Tag ref={ref as any} className={`fm-reveal ${className}`}>{children}</Tag>;
}
