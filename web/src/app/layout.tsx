import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { PwaRegister } from "@/components/PwaRegister";
import { AppHeader, RunModeFooter } from "@/components/shell";
import { fontVars } from "./fonts";

export const metadata: Metadata = {
  title: "Tech Bazaar",
  description: "A refereed arena where seller agents bid for a buyer's computer gear.",
  appleWebApp: { capable: true, title: "Bazaar", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = { themeColor: "#f1e7d3" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`h-full antialiased ${fontVars}`}>
      <body className="min-h-full pb-12">
        <Providers>
          <AppHeader />
          <main className="mx-auto max-w-[1360px] px-4 py-6">{children}</main>
          <RunModeFooter />
          <PwaRegister />
        </Providers>
      </body>
    </html>
  );
}
