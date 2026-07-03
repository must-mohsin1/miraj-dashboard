import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";
import { ThemeProvider } from "@/components/theme-provider";
import { Providers } from "@/components/providers";
import { ServiceWorkerRegister } from "@/components/service-worker-register";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Miraj Dashboard",
  description: "Algorithmic trading analytics dashboard",
  manifest: "/manifest.json",
  themeColor: "#10b981",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Miraj Dashboard",
  },
};

export const viewport = {
  themeColor: "#10b981",
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
        <meta name="theme-color" content="#10b981" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="Miraj Dashboard" />
      </head>
      <body className={`${inter.variable} font-sans`}>
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
