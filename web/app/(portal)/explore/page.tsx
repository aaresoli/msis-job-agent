import { Search } from "lucide-react";
import Link from "next/link";

import { DiscoveryTabs } from "@/components/discovery-tabs";
import { apiGet } from "@/lib/server-api";
import type {
  DiscoveryFacetCount,
  DiscoveryJobsResponse,
  DiscoveryTaxonomy,
} from "@/lib/types";

// Mirrors the query parameters of GET /api/v1/discovery/jobs. The facet
// parameters repeat, so they arrive as arrays when more than one box is ticked.
type SearchParams = {
  q?: string;
  location?: string;
  track?: string;
  concentration?: string | string[];
  role?: string | string[];
  source?: string | string[];
  remote?: string;
  sponsorship?: string;
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
  if (params.location) query.set("location", params.location);
  if (params.track) query.set("track", params.track);
  if (params.sort) query.set("sort", params.sort);
  if (params.remote === "true") query.set("remote", "true");
  if (params.sponsorship === "true") query.set("sponsorship", "true");
  for (const value of asList(params.concentration)) {
    query.append("concentration", value);
  }
  for (const value of asList(params.role)) query.append("role", value);
  for (const value of asList(params.source)) query.append("source", value);
  query.set("limit", String(PAGE_SIZE));
  return query;
}

function FacetGroup({
  legend,
  name,
  options,
  selected,
}: {
  legend: string;
  name: string;
  options: DiscoveryFacetCount[];
  selected: string[];
}) {
  if (!options.length) return null;
  return (
    <fieldset className="paper-card p-5">
      <legend className="eyebrow px-1">{legend}</legend>
      <div className="flex flex-col gap-2 mt-3">
        {options.map((option) => (
          <label className="flex items-center gap-2 text-sm" key={option.name}>
            <input
              type="checkbox"
              name={name}
              value={option.name}
              defaultChecked={selected.includes(option.name)}
            />
            <span className="grow">{option.name}</span>
            {/* Counts come from the unfiltered set so they stay meaningful
                while individual boxes in this group are toggled. */}
            <span className="text-muted tabular-nums">{option.count}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default async function ExplorePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const [data, taxonomy] = await Promise.all([
    apiGet<DiscoveryJobsResponse>(
      `/api/v1/discovery/jobs?${buildQuery(params).toString()}`,
    ),
    apiGet<DiscoveryTaxonomy>("/api/v1/discovery/taxonomy"),
  ]);

  const jobs = data?.jobs ?? [];
  const facets = data?.facets;
  const total = data?.total ?? 0;
  const tracks = taxonomy?.tracks ?? [];
  const selectedConcentrations = asList(params.concentration);
  const selectedRoles = asList(params.role);
  const selectedSources = asList(params.source);

  return (
    <div className="shell py-12">
      <p className="eyebrow">The opportunity index</p>
      <h1 className="text-6xl mt-2">Explore with intent.</h1>
      <DiscoveryTabs active="jobs" />

      <form className="grid lg:grid-cols-[18rem_1fr] gap-6 mt-6 items-start">
        <div className="flex flex-col gap-4">
          <fieldset className="paper-card p-5">
            <legend className="eyebrow px-1">Search</legend>
            <div className="flex flex-col gap-3 mt-3">
              <label className="sr-only" htmlFor="q">
                Role, company, or skill
              </label>
              <input
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="q"
                name="q"
                defaultValue={params.q}
                placeholder="Role, company, or skill"
              />
              <label className="sr-only" htmlFor="location">
                Location
              </label>
              <input
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="location"
                name="location"
                defaultValue={params.location}
                placeholder="Location"
              />
              <label className="sr-only" htmlFor="track">
                Career track
              </label>
              <select
                className="bg-white/60 border border-black/20 px-4 py-3"
                id="track"
                name="track"
                defaultValue={params.track ?? ""}
              >
                <option value="">All tracks</option>
                {tracks.map((track) => (
                  <option key={track} value={track}>
                    {track}
                    {facets?.tracks?.[track] != null
                      ? ` (${facets.tracks[track]})`
                      : ""}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  name="remote"
                  value="true"
                  defaultChecked={params.remote === "true"}
                />
                Remote or hybrid
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  name="sponsorship"
                  value="true"
                  defaultChecked={params.sponsorship === "true"}
                />
                Sponsorship signal stated
              </label>
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
                <option value="company">Company A–Z</option>
              </select>
              <button className="button-primary">
                <Search size={16} /> Search the index
              </button>
            </div>
          </fieldset>

          <FacetGroup
            legend="Concentration"
            name="concentration"
            options={facets?.concentrations ?? []}
            selected={selectedConcentrations}
          />
          <FacetGroup
            legend="Target role"
            name="role"
            options={facets?.roles ?? []}
            selected={selectedRoles}
          />
          <FacetGroup
            legend="Source"
            name="source"
            options={facets?.sources ?? []}
            selected={selectedSources}
          />
        </div>

        <div>
          <p className="text-sm text-muted mb-4">
            {total} opportunities in this view
            {jobs.length < total ? ` · showing first ${jobs.length}` : ""}
          </p>
          <div className="grid xl:grid-cols-2 gap-4">
            {jobs.map((job) => (
              <Link
                href={`/jobs/${job.job_key}`}
                key={job.job_key}
                className="paper-card p-6 hover:-translate-y-1 transition-transform"
              >
                <p className="eyebrow">{job.company}</p>
                <h2 className="text-3xl mt-2">{job.title}</h2>
                <p className="text-muted mt-2">
                  {job.location || "Location not stated"}
                  {job.location_type ? ` · ${job.location_type}` : ""}
                </p>
                {/* Provenance is a compliance requirement, not decoration:
                    every card states where the posting came from. */}
                <p className="text-sm text-muted mt-1">
                  {job.source_badge || job.source}
                  {job.source_attribution ? ` · ${job.source_attribution}` : ""}
                </p>
                {job.opt_cpt_flag == null && (
                  <p className="text-sm text-muted mt-2">
                    Work authorization signal: unknown — review the employer
                    language before applying.
                  </p>
                )}
                <div className="flex flex-wrap gap-2 mt-5">
                  {job.career_track && (
                    <span className="tag">{job.career_track}</span>
                  )}
                  {(job.concentration_tags ?? []).slice(0, 2).map((tag) => (
                    <span className="tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
          {!jobs.length && (
            <div className="paper-card p-10 text-center">
              <h2 className="text-3xl">No jobs in this view yet.</h2>
              <p className="text-muted mt-2">
                Try a broader search or check source health with your
                administrator.
              </p>
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
