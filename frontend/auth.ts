import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

const apiUrl =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

declare module "next-auth" {
  interface User {
    accessToken?: string;
    username?: string;
    email?: string;
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
    error: "/login",
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
            return null;
          }


          const res = await fetch(`${apiUrl}/api/v1/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
          });


          if (!res.ok) {
            return null;
          }

          const data = (await res.json()) as {
            access_token: string;
            token_type: string;
          };

          if (!data?.access_token) {
            return null;
          }

          // Fetch user profile
          const meRes = await fetch(`${apiUrl}/api/v1/auth/me`, {
            headers: { Authorization: "Bearer " + data.access_token },
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

          // Fall back if /me unavailable
          return {
            id: username,
            username,
            accessToken: data.access_token,
          };
        } catch (error) {
          return null;
        }
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = user.accessToken;
        token.username = user.username;
        token.email = user.email;
        token.userId = user.userId;
      }
      return token;
    },
    async session({ session, token }) {
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
