import { Bell, BriefcaseBusiness, Compass, MessageSquareText, Radar, UserRound } from "lucide-react";
import Link from "next/link";
import { LogoutButton } from "@/components/logout-button";

const links = [
  ["Today", "/today", Compass],
  ["Explore", "/explore", BriefcaseBusiness],
  ["My search", "/applications", Radar],
  ["Coach", "/coach", MessageSquareText],
  ["Profile", "/profile", UserRound],
] as const;

export function Nav() {
  return (
    <header className="border-b border-black/15 bg-[#f2eee4]/90 backdrop-blur sticky top-0 z-30">
      <div className="shell h-[74px] flex items-center justify-between gap-6">
        <Link href="/today" className="display text-2xl">HOPE<span className="text-[#7a170f]">.</span></Link>
        <nav aria-label="Primary" className="hidden md:flex items-center gap-1">
          {links.map(([label, href, Icon]) => (
            <Link key={href} href={href} className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/5">
              <Icon size={16} aria-hidden />{label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center"><Link href="/notifications" aria-label="Notifications" className="p-2"><Bell size={19} /></Link><LogoutButton /></div>
      </div>
      <nav aria-label="Mobile" className="md:hidden grid grid-cols-5 border-t border-black/10">
        {links.map(([label, href, Icon]) => (
          <Link key={href} href={href} className="flex flex-col items-center gap-1 py-2 text-[11px]">
            <Icon size={17} aria-hidden />{label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
