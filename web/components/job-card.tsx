"use client";

import { ArrowUpRight, Bookmark, MapPin, X } from "lucide-react";
import Link from "next/link";
import { browserApi, csrfToken } from "@/lib/api";
import { matchBand } from "@/lib/match";
import type { Match } from "@/lib/types";

export function JobCard({ match, index = 0 }: { match: Match; index?: number }) {
  const job = match.job;
  async function feedback(action: "saved" | "dismissed") {
    await browserApi(`/api/v1/jobs/${job.id}/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ action }),
    });
  }
  return (
    <article className="paper-card p-6 sm:p-7 reveal" style={{ animationDelay: `${index * 80}ms` }}>
      <div className="flex gap-5 justify-between items-start">
        <div>
          <p className="eyebrow">{job.company}</p>
          <h2 className="text-3xl mt-2"><Link href={`/jobs/${job.id}`}>{job.title}</Link></h2>
          <p className="flex items-center gap-2 text-[#686258] mt-2"><MapPin size={15} />{job.location || "Location not stated"}</p>
        </div>
        <div className="score-ring shrink-0" style={{ "--score": `${Math.round(match.score)}%` } as React.CSSProperties} aria-label={`${Math.round(match.score)} percent match`}><span>{Math.round(match.score)}</span></div>
      </div>
      <p className="mt-6 text-[#3d3933] leading-relaxed"><strong>Why it fits:</strong> {match.explanation || "Your profile and this role share several relevant signals."}</p>
      <p className="mt-2 text-sm font-semibold text-[#7a1705]">{matchBand(match.score, match.status === "degraded")}</p>
      {job.opt_cpt_flag == null && <p className="mt-3 text-sm text-[#686258]">Work authorization signal: unknown — review the employer language before applying.</p>}
      <div className="flex flex-wrap gap-2 mt-5">{job.concentration_tags.slice(0, 3).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>
      <div className="rule mt-6 pt-4 flex justify-between items-center gap-3">
        <div className="flex gap-2"><button className="button-quiet" onClick={() => feedback("saved")} aria-label="Save job"><Bookmark size={16} /></button><button className="button-quiet" onClick={() => feedback("dismissed")} aria-label="Dismiss job"><X size={16} /></button></div>
        <Link href={`/jobs/${job.id}`} className="font-semibold flex items-center gap-2">Open dossier <ArrowUpRight size={16} /></Link>
      </div>
    </article>
  );
}
