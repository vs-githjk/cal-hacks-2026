import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { AgentPip } from "@/components/AgentPip";
import { PwaRegister } from "@/components/PwaRegister";
import { Sidebar, TopBar, BottomTabs, RunModeFooter } from "@/components/shell";
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
      <body className="min-h-full bg-canvas pb-[calc(4.5rem+env(safe-area-inset-bottom))] text-ink lg:pb-0">
        <Providers>
          <div className="flex min-h-screen flex-col lg:flex-row">
            <Sidebar />
            <div className="min-w-0 flex-1">
              <TopBar />
              <main className="mx-auto w-full max-w-[1200px] px-4 pb-6 pt-5 lg:px-8 lg:pb-10 lg:pt-8">{children}</main>
              <RunModeFooter />
            </div>
          </div>
          <BottomTabs />
          <PwaRegister />
        </Providers>
        <AgentPip />
      </body>
    </html>
  );
}
