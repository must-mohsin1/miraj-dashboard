import { auth } from "@/auth";
import type { Session } from "next-auth";

/**
 * Server-side helper for retrieving the current session and access token.
 * Use inside Server Components / Route Handlers / Server Actions only.
 *
 * @example
 *   const { session, token } = await getSessionAndToken();
 *   if (!session) redirect("/login");
 *   const res = await fetch(`${apiUrl}/api/v1/portfolios`, {
 *     headers: { Authorization: `Bearer ${token}` },
 *   });
 */
export async function getSessionAndToken(): Promise<{
  session: Session | null;
  token: string | null;
}> {
  const session = await auth();
  const token = session?.accessToken ?? null;
  return { session, token };
}

/** Convenience: returns just the JWT access token, or null when unauthenticated. */
export async function getAccessToken(): Promise<string | null> {
  const session = await auth();
  console.log("[auth] getAccessToken: session exists:", !!session, "accessToken exists:", !!session?.accessToken);
  return session?.accessToken ?? null;
}

/** Return true when the user has an authenticated session. */
export async function isAuthenticated(): Promise<boolean> {
  const session = await auth();
  return Boolean(session?.accessToken);
}
