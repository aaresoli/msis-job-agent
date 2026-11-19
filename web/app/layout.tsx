import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "HOPE Career Intelligence", template: "%s · HOPE" },
  description: "Evidence-led career intelligence for Kelley MSIS students",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/hope-mark.svg", apple: "/hope-mark.svg" },
  appleWebApp: { capable: true, title: "HOPE" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
