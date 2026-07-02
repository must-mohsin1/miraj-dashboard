import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";
import { ThemeProvider } from "@/components/theme-provider";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Miraj Dashboard",
  description: "Algorithmic trading analytics dashboard",
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
      <body className={`${inter.variable} font-sans`}>
        <ThemeProvider>
          <AppShell email={session?.user?.email}>{children}</AppShell>
        </ThemeProvider>
      </body>
    </html>
  );
}
