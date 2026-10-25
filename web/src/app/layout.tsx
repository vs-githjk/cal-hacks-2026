import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { PwaRegister } from "@/components/PwaRegister";
import { AppHeader } from "@/components/shell";
import { fontVars } from "./fonts";
import { BRAND, BRAND_SHORT, TAGLINE } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: BRAND, template: `%s · ${BRAND}` },
  description: TAGLINE,
  applicationName: BRAND,
  appleWebApp: { capable: true, title: BRAND_SHORT, statusBarStyle: "default" },
  openGraph: { title: BRAND, description: TAGLINE, siteName: BRAND },
  icons: { apple: "/icons/apple-touch-icon.png" },
};

export const viewport: Viewport = { themeColor: "#eef3f8" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`h-full antialiased ${fontVars}`}>
      <body className="min-h-full">
        <Providers>
          <AppHeader />
          <main className="mx-auto max-w-[1360px] px-4 py-6">{children}</main>
          <PwaRegister />
        </Providers>
      </body>
    </html>
  );
}
