"use client";

import { useEffect, useState } from "react";

/**
 * useMediaQuery — Client Component hook.
 *
 * Returns a boolean indicating whether the given CSS media query currently
 * matches. SSR-safe: always returns `false` on the server and during the
 * first client render to avoid hydration mismatches, then updates to the
 * real value after mount.
 *
 * @example
 *   const isMobile = useMediaQuery("(max-width: 768px)");
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;

    const mql = window.matchMedia(query);
    // Set the initial real value immediately after mount.
    setMatches(mql.matches);

    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);

    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}

export default useMediaQuery;
