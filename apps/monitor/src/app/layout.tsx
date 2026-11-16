import type { CSSProperties } from "react";
import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OHush",
  description: "Take Down Big Audio",
};

export const viewport = {
  themeColor: "#ffffff",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  // iOS auto-link detection rewrites text into <a> tags and breaks hydration.
  formatDetection: {
    telephone: false,
    date: false,
    email: false,
    address: false,
  },
} as Viewport;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:wght@500;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className="antialiased"
        style={
          {
            ["--font-display"]: '"Fraunces", Georgia, serif',
            ["--font-mono"]: '"IBM Plex Mono", ui-monospace, monospace',
          } as CSSProperties
        }
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
