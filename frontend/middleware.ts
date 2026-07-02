import NextAuth from "next-auth";
export { auth as middleware } from "@/auth";

/**
 * Protect every route except the auth pages.
 *
 * Auth.js v5's `auth` middleware export handles the session check; the
 * `config.matcher` below ensures it runs on every path *except*
 * `/login`, `/register`, and Next.js internals.
 */

export const config = {
  matcher: [
    /*
     * Run auth on all paths except:
     * - /login, /register          (public auth pages)
     * - /api/auth/*               (Auth.js route handlers)
     * - /_next/*, /favicon.ico, …  (static assets)
     */
    "/((?!login|register|api/auth|_next/static|_next/image|favicon.ico).*)",
  ],
};
