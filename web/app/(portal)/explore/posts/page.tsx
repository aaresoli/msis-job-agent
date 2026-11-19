import { ArrowUpRight, Search } from "lucide-react";

import { DiscoveryTabs } from "@/components/discovery-tabs";
import { apiGet } from "@/lib/server-api";
import type {
  DiscoveryFacetCount,
  DiscoveryPostStats,
  DiscoveryPostsResponse,
} from "@/lib/types";

// Mirrors the query parameters of GET /api/v1/discovery/posts.
type SearchParams = {
  q?: string;
  company?: string;
  concentration?: string | string[];
  sort?: string;
};

const PAGE_SIZE = 60;

function asList(value: string | string[] | undefined): string[] {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

function buildQuery(params: SearchParams): URLSearchParams {
  const query = new URLSearchParams();
  if (params.q) query.set("q", params.q);
  if (params.company) query.set("company", params.company);
  if (params.sort) query.set("sort", params.sort);
  for (const value of asList(params.concentration)) {
    query.append("concentration", value);
  }
  query.set("limit", String(PAGE_SIZE));
  return query;
}

function ConcentrationFacets({
  options,
  selected,
}: {
  options: DiscoveryFacetCount[];
  selected: string[];
}) {
  if (!options.length) return null;
  return (
    <fieldset className="paper-card p-5">
      <legend className="eyebrow px-1">Concentration</legend>
      <div className="flex flex-col gap-2 mt-3">
        {options.map((option) => (
          <label className="flex items-center gap-2 text-sm" key={option.name}>
            <input
              type="checkbox"
              name="concentration"
              value={option.name}
              defaultChecked={selected.includes(option.name)}
            />
            <span className="grow">{option.name}</span>
            <span className="text-muted tabular-nums">{option.count}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default async function PostsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const [data, stats] = await Promise.all([
    apiGet<DiscoveryPostsResponse>(
      `/api/v1/discovery/posts?${buildQuery(params).toString()}`,
    ),
    apiGet<DiscoveryPostStats>("/api/v1/discovery/posts/stats"),
  ]);

  const posts = data?.posts ?? [];
  const total = data?.total ?? 0;
  const selectedConcentrations = asList(params.concentration);

  return (
    <div className="shell py-12">
      <p className="eyebrow">The opportunity index</p>
      <h1 className="text-6xl mt-2">Hiring posts, sourced.</h1>
      <DiscoveryTabs active="posts" />

      {stats && (
        <p className="text-sm text-muted mt-6">
          {stats.total_posts} posts from {stats.company_count} companies ·{" "}
          {stats.new_this_week} new this week · {stats.with_opportunity} carry a
          hiring signal
        </p>
      )}

      <form className="grid lg:grid-cols-[18rem_1fr] gap-6 mt-6 items-start">
        <div className="flex flex-col gap-4">
          <fieldset className="paper-card p-5">
            <legend className="eyebrow px-1">Search</legend>
            <div className="flex flex-col gap-3 mt-3">
              <label className="sr-only" htmlFor="q">
                Keyword
              </label>
              <input
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="q"
                name="q"
                defaultValue={params.q}
                placeholder="Keyword or role"
              />
              <label className="sr-only" htmlFor="company">
                Company
              </label>
              <input
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="company"
                name="company"
                defaultValue={params.company}
                placeholder="Company"
              />
              <label className="sr-only" htmlFor="sort">
                Sort
              </label>
              <select
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="sort"
                name="sort"
                defaultValue={params.sort ?? ""}
              >
                <option value="">Most relevant</option>
                <option value="recent">Most recent</option>
              </select>
              <button className="button-primary">
                <Search size={16} /> Search posts
              </button>
            </div>
          </fieldset>

          <ConcentrationFacets
            options={data?.facets?.concentrations ?? []}
            selected={selectedConcentrations}
          />
        </div>

        <div>
          <p className="text-sm text-muted mb-4">
            {total} posts in this view
            {posts.length < total ? ` · showing first ${posts.length}` : ""}
          </p>
          <div className="grid xl:grid-cols-2 gap-4">
            {posts.map((post) => (
              <article className="paper-card p-6" key={post.post_key}>
                <p className="eyebrow">
                  {post.company_name || post.author_name || "Unattributed"}
                </p>
                {post.published_at && (
                  <p className="text-sm text-muted mt-1">{post.published_at}</p>
                )}
                <p className="leading-relaxed mt-4">{post.content_excerpt}</p>
                {post.has_signal && post.signal_summary && (
                  <p className="text-sm mt-4">
                    <strong>Signal:</strong> {post.signal_summary}
                  </p>
                )}
                <div className="flex flex-wrap gap-2 mt-5">
                  {(post.concentration_tags ?? []).slice(0, 3).map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
                {/* Every post links back to its source. The compliance rule is
                    that post-derived claims stay traceable to the original. */}
                <div className="rule mt-6 pt-4">
                  <a
                    className="flex items-center gap-2 font-semibold"
                    href={post.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original post <ArrowUpRight size={15} />
                  </a>
                </div>
              </article>
            ))}
          </div>
          {!posts.length && (
            <div className="paper-card p-10 text-center">
              <h2 className="text-3xl">No hiring posts in this view.</h2>
              <p className="text-muted mt-2">
                Post-derived intelligence stays off until an approved feed is
                connected. Broaden the search if a feed is already running.
              </p>
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
