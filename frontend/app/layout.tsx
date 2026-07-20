import type { Metadata } from "next";
import { Fraunces, JetBrains_Mono } from "next/font/google";
import "./globals.css";

import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";
import { ThemeProvider } from "@/components/theme-provider";
import { Providers } from "@/components/providers";
import { ServiceWorkerRegister } from "@/components/service-worker-register";

// INK & OXIDE voices (DESIGN.md): serif speaks verdicts, sans speaks
// interface, mono speaks numbers. General Sans loads via Fontshare below;
// Fraunces and JetBrains Mono are variable fonts served by next/font.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  axes: ["opsz"],
  display: "swap",
});

const jbmono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jbmono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Miraj Research & Decision Desk",
  description: "The desk prints one judgment a day — verdict-first crypto analysis",
  manifest: "/manifest.json",
  themeColor: "#0F0E0C",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Miraj Desk",
  },
};

export const viewport = {
  themeColor: "#0F0E0C",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Resolve the session server-side so the AppShell can show the signed-in
  // user's email. Unauthenticated routes (login/register) are rendered bare
  // inside AppShell regardless of session state.
  const session = await auth();

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#0F0E0C" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="Miraj Desk" />
        <link href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600&display=swap" rel="stylesheet" />
      </head>
      <body className={`${fraunces.variable} ${jbmono.variable} font-sans`}>
        <ThemeProvider>
          <Providers>
            <AppShell email={session?.user?.email}>{children}</AppShell>
          </Providers>
        </ThemeProvider>
        {/* Register the PWA service worker for offline shell caching */}
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
