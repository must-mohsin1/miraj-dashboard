"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * ThemeSettings — Client Component.
 *
 * A simple dark/light toggle persisted to `localStorage` and applied by
 * toggling the `dark` class on `<html>`. The app defaults to dark theme; the
 * toggle lets the user switch to a light appearance.
 *
 * Theme is purely client-side (no backend round-trip).
 */

const STORAGE_KEY = "miraj-theme";

export function ThemeSettings() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [mounted, setMounted] = useState(false);

  // Initialise from localStorage on mount.
  useEffect(() => {
    setMounted(true);
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
    }
  }, []);

  // Apply theme to <html>.
  useEffect(() => {
    if (!mounted) return;
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme, mounted]);

  function toggle() {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
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
