import Link from "next/link";

/** Jobs and hiring posts are two views of the same discovery index. */
export function DiscoveryTabs({ active }: { active: "jobs" | "posts" }) {
  const tabs = [
    ["jobs", "/explore", "Jobs"],
    ["posts", "/explore/posts", "Hiring posts"],
  ] as const;
  return (
    <nav aria-label="Discovery views" className="flex gap-1 mt-6">
      {tabs.map(([key, href, label]) => (
        <Link
          key={key}
          href={href}
          aria-current={active === key ? "page" : undefined}
          className={
            active === key
              ? "px-4 py-2 border-b-2 border-crimson font-semibold"
              : "px-4 py-2 border-b-2 border-transparent text-muted hover:text-inherit"
          }
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
