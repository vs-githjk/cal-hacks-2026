// web/src/app/fonts.ts
// Geist for UI, Instrument Serif for the one hero number per screen, Geist Mono for codes and timestamps.
// All three are Google Fonts (SIL Open Font License 1.1). next/font downloads at build time; no runtime request.
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";

export const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
export const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
export const instrument = Instrument_Serif({ subsets: ["latin"], weight: "400", variable: "--font-instrument", display: "swap" });

/** Put on <html>: className={`h-full antialiased ${fontVars}`} */
export const fontVars = `${geist.variable} ${geistMono.variable} ${instrument.variable}`;
