// web/src/app/fonts.ts
// Design system v2: Geist for everything, Geist Mono for prices, codes and timestamps (both SIL OFL 1.1, via next/font).
import { Geist, Geist_Mono } from "next/font/google";

export const geist = Geist({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-geist", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-geist-mono", display: "swap" });

/** Put on <html>: className={`h-full antialiased ${fontVars}`} */
export const fontVars = `${geist.variable} ${geistMono.variable}`;
