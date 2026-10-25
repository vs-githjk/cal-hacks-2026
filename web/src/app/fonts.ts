// web/src/app/fonts.ts
// Geist for UI, Cinzel for display (titles, the question, numerals), Geist Mono for codes and timestamps.
// All three are Google Fonts (SIL Open Font License 1.1). next/font downloads at build time; no runtime request.
import { Geist, Geist_Mono, Cinzel } from "next/font/google";

export const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
export const cinzel = Cinzel({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-cinzel", display: "swap" });

/** Put on <html>: className={`h-full antialiased ${fontVars}`} */
export const fontVars = `${geist.variable} ${geistMono.variable} ${cinzel.variable}`;
