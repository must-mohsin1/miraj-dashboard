"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ThemeProviderProps } from "next-themes";

/**
 * ThemeProvider — thin wrapper around next-themes' ThemeProvider.
 *
 * - `attribute="class"` → toggles the `dark` class on `<html>`, matching the
 *   existing Tailwind `dark:` variant setup.
 * - `defaultTheme="dark"` preserves the current default.
 * - `enableSystem={false}` initially (system-theme follow can be enabled
 *   later if desired).
 * - `disableTransitionOnChange` avoids a flash of intermediate colours when
 *   switching themes.
 */
export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem={false}
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}

export default ThemeProvider;
