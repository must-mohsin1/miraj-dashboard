"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";

/**
 * ThemeSettings — Client Component.
 *
 * A dark/light toggle backed by `next-themes` (replaces the previous
 * hand-rolled `localStorage` + class-toggle). `next-themes` handles SSR
 * (no flash of incorrect theme), persistence to `localStorage`, and
 * provides a single source of truth via the `useTheme()` hook.
 *
 * Theme is purely client-side (no backend round-trip).
 */

export function ThemeSettings() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // next-themes recommends a `mounted` guard to avoid hydration mismatch.
  useEffect(() => {
    setMounted(true);
  }, []);

  function toggle() {
    setTheme(theme === "dark" ? "light" : "dark");
  }

  if (!mounted) {
    // Avoid hydration mismatch — render the dark (default) state.
    return (
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <Moon className="h-5 w-5" />
        Dark mode
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-sm text-slate-300">
          {theme === "dark" ? (
            <>
              <Moon className="h-5 w-5 text-slate-400" />
              <span>Dark mode</span>
            </>
          ) : (
            <>
              <Sun className="h-5 w-5 text-amber-400" />
              <span>Light mode</span>
            </>
          )}
        </div>
        <button
          role="switch"
          aria-checked={theme === "dark"}
          aria-label="Toggle dark mode"
          onClick={toggle}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
            theme === "dark"
              ? "bg-emerald-600"
              : "bg-slate-600"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              theme === "dark" ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>
      <p className="text-xs text-slate-500">
        The dashboard defaults to dark mode. Toggle to switch to a light theme.
      </p>
    </div>
  );
}

export default ThemeSettings;
