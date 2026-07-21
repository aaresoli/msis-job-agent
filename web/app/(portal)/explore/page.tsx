import { Search } from "lucide-react";
import Link from "next/link";

import { apiGet } from "@/lib/server-api";
import type { Job } from "@/lib/types";

type SearchParams = {
  q?: string;
  location?: string;
  concentration?: string;
  seniority?: string;
  remote?: string;
  sponsorship_signal?: string;
  source?: string;
  fresh_days?: string;
};

export default async function ExplorePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value);
  }
  const data = await apiGet<{ items: Job[] }>(
    `/api/v1/jobs?${query.toString()}`,
  );
  const jobs = data?.items ?? [];
  return (
    <div className="shell py-12">
      <p className="eyebrow">The opportunity index</p>
      <h1 className="text-6xl mt-2">Explore with intent.</h1>
      <form className="paper-card p-4 my-8 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="sr-only" htmlFor="q">Role, company, or skill</label>
        <input className="bg-white/60 border border-black/20 px-4 py-3 lg:col-span-2" id="q" name="q" defaultValue={params.q} placeholder="Role, company, or skill" />
        <label className="sr-only" htmlFor="location">Location</label>
        <input className="bg-white/60 border border-black/20 px-4 py-3" id="location" name="location" defaultValue={params.location} placeholder="Location" />
        <select aria-label="Concentration" name="concentration" defaultValue={params.concentration ?? ""} className="bg-white/60 border border-black/20 px-4 py-3"><option value="">All concentrations</option><option>Business Intelligence and Analytics</option><option>Enterprise Security and Risk Management</option><option>Digital Enterprise Systems</option><option>Enterprise Data Management</option><option>Intelligent Systems Engineering</option></select>
        <select aria-label="Seniority" name="seniority" defaultValue={params.seniority ?? ""} className="bg-white/60 border border-black/20 px-4 py-3"><option value="">All seniority</option><option value="entry">Entry</option><option value="intern">Intern</option><option value="mid">Mid</option></select>
        <select aria-label="Work authorization signal" name="sponsorship_signal" defaultValue={params.sponsorship_signal ?? ""} className="bg-white/60 border border-black/20 px-4 py-3"><option value="">Any work-auth signal</option><option value="positive">Positive signal</option><option value="restriction">Restriction stated</option><option value="unknown">Unknown</option></select>
        <select aria-label="Freshness" name="fresh_days" defaultValue={params.fresh_days ?? ""} className="bg-white/60 border border-black/20 px-4 py-3"><option value="">Any freshness</option><option value="7">Past 7 days</option><option value="30">Past 30 days</option><option value="90">Past 90 days</option></select>
        <label className="flex items-center gap-2 border border-black/20 px-4 py-3"><input type="checkbox" name="remote" value="true" defaultChecked={params.remote === "true"} /> Remote or hybrid</label>
        <button className="button-primary lg:col-span-4"><Search size={16} /> Search the index</button>
      </form>
      <p className="text-sm text-muted mb-4">{jobs.length} opportunities in this view</p>
      <div className="grid lg:grid-cols-2 gap-4">{jobs.map((job) => <Link href={`/jobs/${job.id}`} key={job.id} className="paper-card p-6 hover:-translate-y-1 transition-transform"><p className="eyebrow">{job.company}</p><h2 className="text-3xl mt-2">{job.title}</h2><p className="text-muted mt-2">{job.location || "Location not stated"} · {job.source}</p><div className="flex gap-2 mt-5">{job.concentration_tags.slice(0, 2).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div></Link>)}</div>
      {!jobs.length && <div className="paper-card p-10 text-center"><h2 className="text-3xl">No jobs in this view yet.</h2><p className="text-muted mt-2">Try a broader search or check source health with your administrator.</p></div>}
    </div>
  );
}
