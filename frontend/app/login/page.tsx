import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { LoginForm } from "@/components/login-form";

export const metadata: Metadata = {
  title: "Log in — Miraj Dashboard",
};

export default async function LoginPage() {
  // Already-authenticated users are sent to the dashboard root.
  const session = await auth();
  if (session) {
    redirect("/");
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <LoginForm />
    </main>
  );
}
