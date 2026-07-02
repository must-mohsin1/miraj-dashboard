import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";

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
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={`${inter.variable} font-sans`}>
        <AppShell email={session?.user?.email}>{children}</AppShell>
      </body>
    </html>
  );
}
