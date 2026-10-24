import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { AgentPip } from "@/components/AgentPip";
import { AppHeader, RunModeFooter } from "@/components/shell";
import { fontVars } from "./fonts";

export const metadata: Metadata = {
  title: "Tech Bazaar",
  description: "A refereed arena where seller agents bid for a buyer's computer gear.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`h-full antialiased ${fontVars}`}>
      <body className="min-h-full pb-12">
        <Providers>
          <AppHeader />
          <main className="mx-auto max-w-[1360px] px-4 py-6">{children}</main>
          <RunModeFooter />
        </Providers>
        <AgentPip />
      </body>
    </html>
  );
}
