"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Sidebar, navItems } from "@/components/sidebar";
import { Header } from "@/components/header";
import { useMediaQuery } from "@/hooks/use-media-query";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetHeader,
} from "@/components/ui/sheet";

/**
 * AppShell — Client Component.
 *
 * The top-level application chrome: renders the Sidebar + Header + main content
 * area for authenticated pages. Uses `usePathname()` to highlight the active
 * nav item and derive the current page title shown in the header.
 *
 * Responsive behaviour:
 *  - Desktop (md+ / ≥768px): renders the fixed `<Sidebar>` as-is (256px expanded
 *    or 64px collapsed). The header shows the app title + page name.
 *  - Mobile (<768px): the fixed sidebar is hidden; a hamburger button in the
 *    `<Header>` opens a `<Sheet>` from the left containing the nav. The sheet
 *    auto-closes on route change.
 *
 * Auth-only routes (`/login`, `/register`) bypass the shell entirely and render
 * their content full-width.
 */

/** Routes that should render WITHOUT the sidebar/header chrome. */
const SHELL_EXCLUDED_ROUTES = new Set(["/login", "/register"]);

function getPageTitle(pathname: string): string {
  const match = navItems.find(({ href }) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  });
  return match?.label ?? "Dashboard";
}

export function AppShell({
  email,
  children,
}: {
  email?: string | null;
  children: ReactNode;
}) {
  const pathname = usePathname() ?? "/";
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isDesktop = useMediaQuery("(min-width: 768px)");

  // Login / register pages render bare (no sidebar / header).
  if (SHELL_EXCLUDED_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  const pageTitle = getPageTitle(pathname);

  // Close the mobile sheet whenever the route changes.
  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Desktop sidebar (hidden below md) */}
      <Sidebar
        activePath={pathname}
        email={email}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        variant="desktop"
      />

      {/* Mobile sidebar in a Sheet (only rendered when not desktop) */}
      {!isDesktop && (
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent
            side="left"
            className="w-64 p-0 border-slate-800 bg-slate-900"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>Navigation</SheetTitle>
            </SheetHeader>
            <Sidebar
              activePath={pathname}
              email={email}
              collapsed={false}
              onToggle={() => setCollapsed((c) => !c)}
              variant="mobile"
            />
          </SheetContent>
        </Sheet>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          pageTitle={pageTitle}
          isDesktop={isDesktop}
          onHamburgerClick={() => setMobileOpen(true)}
        />
        <main className="flex-1 overflow-y-auto p-3 sm:p-6">{children}</main>
      </div>

      {/* Close the mobile sidebar on route change */}
      <RouteChangeWatcher onRouteChange={() => setMobileOpen(false)} />
    </div>
  );
}

/**
 * Tiny helper component that calls `onRouteChange` whenever `usePathname()`
 * changes. Kept separate from AppShell so the main render doesn't need a
 * `useEffect` dependency on `pathname` (which would force a re-render pass).
 */
function RouteChangeWatcher({
  onRouteChange,
}: {
  onRouteChange: () => void;
}) {
  const pathname = usePathname();
  useEffect(() => {
    onRouteChange();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
  return null;
}

export default AppShell;
