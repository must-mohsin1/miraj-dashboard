import { cn } from "@/lib/utils";
import { Menu } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * Header — Client Component (due to isDesktop/onHamburgerClick props).
 *
 * A slim top bar showing:
 *  - On desktop (md+): the application title on the left and the current page
 *    name on the right.
 *  - On mobile (<md): a hamburger button on the left that opens the sidebar
 *    Sheet, and the current page name next to it.
 *
 * `isDesktop` and `onHamburgerClick` are passed via props from<AppShell>.
 */

export function Header({
  pageTitle,
  isDesktop = true,
  onHamburgerClick,
  className,
}: {
  pageTitle: string;
  isDesktop?: boolean;
  onHamburgerClick?: () => void;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900 px-3 sm:px-6",
        className
      )}
    >
      <div className="flex items-center gap-2">
        {/* Hamburger — only on mobile */}
        {!isDesktop && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onHamburgerClick}
            aria-label="Open navigation menu"
            className="min-h-11 min-w-11 text-slate-300 hover:bg-slate-800 hover:text-slate-100"
          >
            <Menu className="h-5 w-5" />
          </Button>
        )}
        <span className="text-base font-semibold tracking-tight text-slate-100">
          {isDesktop ? "Crypto Analysis" : pageTitle}
        </span>
      </div>
      {isDesktop && (
        <nav className="text-sm text-slate-400" aria-label="Breadcrumb">
          <span className="font-medium text-slate-300">{pageTitle}</span>
        </nav>
      )}
    </header>
  );
}

export default Header;
