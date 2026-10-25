import type { MetadataRoute } from "next";

// The dashboard lives under /buyer, so the installed app opens there. Colours are the cream canvas.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Tech Bazaar",
    short_name: "Bazaar",
    description: "A refereed arena where seller agents bid for a buyer's computer gear.",
    start_url: "/buyer",
    scope: "/",
    display: "standalone",
    background_color: "#F5EFE6",
    theme_color: "#F5EFE6",
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
