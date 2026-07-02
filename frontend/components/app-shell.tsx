"use client";

import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Sidebar, navItems } from "@/components/sidebar";
import { Header } from "@/components/header";

/**
 * AppShell — Client Component.
 *
 * The top-level application chrome: renders the Sidebar + Header + main content
 * area for authenticated pages. Uses `usePathname()` to highlight the active
 * nav item and derive the current page title shown in the header.
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

  // Login / register pages render bare (no sidebar / header).
  if (SHELL_EXCLUDED_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  const pageTitle = getPageTitle(pathname);

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <Sidebar
        activePath={pathname}
        email={email}
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header pageTitle={pageTitle} />
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}

export default AppShell;
