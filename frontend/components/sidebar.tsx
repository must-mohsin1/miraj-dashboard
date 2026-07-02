import Link from "next/link";
import {
  Home,
  TrendingUp,
  Search,
  BarChart3,
  Briefcase,
  History,
  Settings,
  ChevronLeft,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { LogoutButton } from "@/components/logout-button";

/**
 * Sidebar navigation — Server Component.
 *
 * Renders the primary navigation for the dashboard. It is driven entirely by
 * props (no client hooks of its own); the active route + collapsed state are
 * owned by the `AppShell` client wrapper and passed down here.
 *
 * The `variant` prop selects the rendering mode:
 *  - `"desktop"` (default): renders a fixed-width `<aside>` (256px expanded or
 *    64px collapsed). Used on `md+` breakpoints.
 *  - `"mobile"`: renders the same nav content but without the surrounding
 *    `<aside>` shell — the `AppShell` wraps it in a `Sheet` so the nav slides
 *    in from the left. The collapse toggle is hidden in mobile mode.
 */

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

export const navItems: NavItem[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/macro", label: "Macro Dashboard", icon: TrendingUp },
  { href: "/scanner", label: "Scanner", icon: Search },
  { href: "/analysis", label: "Analysis", icon: BarChart3 },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/history", label: "History", icon: History },
  { href: "/settings", label: "Settings", icon: Settings },
];

function isActivePath(activePath: string, href: string): boolean {
  if (href === "/") return activePath === "/";
  return activePath === href || activePath.startsWith(`${href}/`);
}

/**
 * The inner nav content — shared between desktop (aside) and mobile (sheet)
 * rendering. Extracted so the same markup is used in both modes.
 */
function SidebarNav({
  activePath,
  email,
  collapsed,
  onToggle,
  variant,
}: {
  activePath: string;
  email?: string | null;
  collapsed: boolean;
  onToggle: () => void;
  variant: "desktop" | "mobile";
}) {
  const isMobile = variant === "mobile";
  return (
    <div className="flex h-full flex-col">
      {/* Brand + collapse toggle */}
      <div className="flex h-14 items-center justify-between gap-2 border-b border-slate-800 px-3">
        {(!collapsed || isMobile) && (
          <span className="truncate text-sm font-semibold text-slate-100">
            Crypto Analysis
          </span>
        )}
        {/* Hide collapse toggle in mobile sheet mode — the Sheet's X handles closing */}
        {!isMobile && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100"
          >
            <ChevronLeft
              className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")}
            />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2" aria-label="Primary">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = isActivePath(activePath, href);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed && !isMobile ? label : undefined}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                "min-h-11",
                collapsed && !isMobile && "justify-center px-0",
                isMobile && "py-2.5",
                active
                  ? "bg-emerald-600/10 text-emerald-400"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {(!collapsed || isMobile) && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* User + logout */}
      <div className="border-t border-slate-800 p-3">
        {(!collapsed || isMobile) && (
          <p className="mb-2 truncate text-xs text-slate-500">
            Signed in as{" "}
            <span className="text-slate-300">{email ?? "user"}</span>
          </p>
        )}
        <LogoutButton collapsed={collapsed && !isMobile} />
      </div>
    </div>
  );
}

export function Sidebar({
  activePath,
  email,
  collapsed,
  onToggle,
  variant = "desktop",
}: {
  activePath: string;
  email?: string | null;
  collapsed: boolean;
  onToggle: () => void;
  variant?: "desktop" | "mobile";
}) {
  // Mobile variant: render just the nav content — the AppShell wraps it in a Sheet.
  if (variant === "mobile") {
    return (
      <SidebarNav
        activePath={activePath}
        email={email}
        collapsed={false}
        onToggle={onToggle}
        variant="mobile"
      />
    );
  }

  // Desktop variant: fixed aside.
  return (
    <aside
      className={cn(
        "hidden md:flex h-screen shrink-0 flex-col border-r border-slate-800 bg-slate-900 transition-[width] duration-200 ease-in-out",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <SidebarNav
        activePath={activePath}
        email={email}
        collapsed={collapsed}
        onToggle={onToggle}
        variant="desktop"
      />
    </aside>
  );
}

export default Sidebar;
