import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { RunModeFooter } from "@/components/RunModeFooter";

export const metadata: Metadata = {
  title: "Tech Bazaar",
  description: "A refereed arena where seller agents bid for a buyer's computer gear.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full pb-12">
        <Providers>
          <header className="border-b border-[var(--line)] bg-[var(--panel)]">
            <nav className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3 text-sm">
              <Link href="/" className="font-semibold tracking-tight">
                Tech Bazaar
              </Link>
              <Link href="/buyer" className="text-[var(--muted)] hover:text-[var(--ink)]">
                Buyer
              </Link>
              <Link href="/market" className="text-[var(--muted)] hover:text-[var(--ink)]">
                Market
              </Link>
            </nav>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
          <RunModeFooter />
        </Providers>
      </body>
    </html>
  );
}
