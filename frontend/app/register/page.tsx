import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { RegisterForm } from "@/components/register-form";

export const metadata: Metadata = {
  title: "Register — Miraj Dashboard",
};

export default async function RegisterPage() {
  // Already-authenticated users are sent to the dashboard root.
  const session = await auth();
  if (session) {
    redirect("/");
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <RegisterForm />
    </main>
  );
}
