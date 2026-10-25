import type { MetadataRoute } from "next";
import { BRAND, BRAND_SHORT, DESCRIPTION } from "@/lib/brand";

// The dashboard lives under /buyer, so the installed app opens there. Colours are the design system v2 canvas; the icons are the Fish Market mark (public/icons/mark.svg).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND,
    short_name: BRAND_SHORT,
    description: DESCRIPTION,
    start_url: "/buyer",
    scope: "/",
    display: "standalone",
    background_color: "#eef3f8",
    theme_color: "#0b1b2b",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Dashboard", url: "/buyer" },
      { name: "Purchases", url: "/buyer/purchases" },
      { name: "Decisions", url: "/buyer/decisions" },
      { name: "Agents", url: "/buyer/agents" },
    ],
  };
}
