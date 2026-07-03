"use client";

import { useEffect, useState } from "react";

/**
 * useClientToken — fetches the JWT access token client-side.
 *
 * useSession() from next-auth/react doesn't always populate accessToken
 * on the client. This hook directly calls /api/auth/session to get it.
 */
export function useClientToken(): string | null {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/session")
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled && data?.user?.accessToken) {
          setToken(data.user.accessToken);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  return token;
}
