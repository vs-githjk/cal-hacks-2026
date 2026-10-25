import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { AgentPip } from "@/components/AgentPip";
import { PwaRegister } from "@/components/PwaRegister";
import { TopNav, RunModeFooter } from "@/components/shell";
import { fontVars } from "./fonts";

export const metadata: Metadata = {
  title: "Tech Bazaar",
  description: "A refereed arena where seller agents bid for a buyer's computer gear.",
  appleWebApp: { capable: true, title: "Bazaar", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = { themeColor: "#F5EFE6" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`h-full antialiased ${fontVars}`}>
      <body className="min-h-full bg-canvas text-ink">
        <Providers>
          <TopNav />
          <main className="mx-auto w-full max-w-[1200px] px-4 py-5 lg:px-8 lg:py-6">{children}</main>
          <RunModeFooter />
          <PwaRegister />
        </Providers>
        <AgentPip />
      </body>
    </html>
  );
}
