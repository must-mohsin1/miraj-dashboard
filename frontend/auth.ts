import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

/**
 * Auth.js v5 configuration.
 *
 * Flow
 * -----
 * 1. `authorize` posts { username, password } to the FastAPI `/api/v1/auth/login`
 *    endpoint which returns `{ access_token, token_type }`.
 * 2. The returned JWT is saved on the JWT token in the `jwt` callback.
 * 3. The `session` callback copies the access token + user info into the
 *    client-visible session so server components / SWR can read it.
 * 4. On initial sign-in the user profile is fetched from `/api/v1/auth/me`
 *    so the session is populated immediately.
 */

const apiUrl =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

declare module "next-auth" {
  interface User {
    /** JWT access token returned by the FastAPI backend. */
    accessToken?: string;
    username?: string;
    email?: string;
    /** Numeric user id from the backend. */
    userId?: string | number;
  }

  interface Session {
    accessToken?: string;
    user?: User;
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    accessToken?: string;
    username?: string;
    email?: string;
    userId?: string | number;
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  providers: [
    Credentials({
      name: "credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        try {
          const username = credentials?.username as string | undefined;
          const password = credentials?.password as string | undefined;
          if (!username || !password) {
            console.error("[auth] Missing username or password");
            return null;
          }

          console.log("[auth] Attempting login for:", username, "to:", `${apiUrl}/api/v1/auth/login`);

          const res = await fetch(`${apiUrl}/api/v1/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
          });

          console.log("[auth] Login response status:", res.status);

          if (!res.ok) {
            console.error("[auth] Login failed:", res.status, await res.text());
            return null;
          }

        const data = (await res.json()) as {
          access_token: string;
          token_type: string;
        };

        if (!data?.access_token) {
          return null;
        }

        // Fetch the user profile so we can populate the session immediately.
        const meRes = await fetch(`${apiUrl}/api/v1/auth/me`, {
          headers: { Authorization: `Bearer ${data.access_token}` },
        });

        if (meRes.ok) {
          const me = (await meRes.json()) as {
            id: number;
            username: string;
            email: string;
          };
          return {
            id: String(me.id),
            userId: me.id,
            username: me.username,
            email: me.email,
            accessToken: data.access_token,
          };
        }

        // Fall back to a minimal user object if `/me` is unavailable.
        return {
          id: username,
          username,
          accessToken: data.access_token,
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      // Initial sign-in: persist the access token + user fields on the token.
      if (user) {
        token.accessToken = user.accessToken;
        token.username = user.username;
        token.email = user.email;
        token.userId = user.userId;
      }
      return token;
    },
    async session({ session, token }) {
      // Expose the token data to the client session.
      if (token.accessToken) {
        session.accessToken = token.accessToken;
      }
      if (session.user) {
        session.user.userId = token.userId;
        session.user.username = token.username;
        if (token.email) {
          session.user.email = token.email;
        }
        session.user.accessToken = token.accessToken;
      }
      return session;
    },
  },
});
