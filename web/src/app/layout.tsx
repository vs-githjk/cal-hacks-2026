import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { PwaRegister } from "@/components/PwaRegister";
import { AppHeader, RunModeFooter } from "@/components/shell";
import { fontVars } from "./fonts";
import { BRAND, BRAND_SHORT, DESCRIPTION } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: BRAND, template: `%s · ${BRAND}` },
  description: DESCRIPTION,
  applicationName: BRAND,
  appleWebApp: { capable: true, title: BRAND_SHORT, statusBarStyle: "default" },
  openGraph: { title: BRAND, description: DESCRIPTION, siteName: BRAND },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = { themeColor: "#eef3f8" };

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
