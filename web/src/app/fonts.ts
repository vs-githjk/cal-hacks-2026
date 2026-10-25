// web/src/app/fonts.ts
// Geist for UI, Bricolage Grotesque for display (titles, the one big number), Geist Mono for codes and timestamps.
// All three are Google Fonts (SIL Open Font License 1.1). next/font downloads at build time; no runtime request.
import { Geist, Geist_Mono, Bricolage_Grotesque, Patrick_Hand } from "next/font/google";

export const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
export const bricolage = Bricolage_Grotesque({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--font-bricolage", display: "swap" });
export const hand = Patrick_Hand({ subsets: ["latin"], weight: "400", variable: "--font-hand", display: "swap" });

/** Put on <html>: className={`h-full antialiased ${fontVars}`} */
export const fontVars = `${geist.variable} ${geistMono.variable} ${bricolage.variable} ${hand.variable}`;
