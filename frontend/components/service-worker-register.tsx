"use client";

import { useEffect } from "react";

/**
 * ServiceWorkerRegister — client component that registers the PWA service worker.
 *
 * Registers `/sw.js` on mount (production only) to enable offline shell
 * caching. In development the SW is skipped to avoid caching issues during
 * hot-reload.
 *
 * Placed at the bottom of the root layout so it runs once on every page.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;

    // Only register in production to avoid dev caching issues.
    if (process.env.NODE_ENV !== "production") return;

    window.addEventListener("load", () => {
      navigator.serviceWorker
        .register("/sw.js")
        .then((registration) => {
          // eslint-disable-next-line no-console
          console.log("[PWA] Service worker registered:", registration.scope);
        })
        .catch((error) => {
          // eslint-disable-next-line no-console
          console.warn("[PWA] Service worker registration failed:", error);
        });
    });
  }, []);

  return null;
}

export default ServiceWorkerRegister;
