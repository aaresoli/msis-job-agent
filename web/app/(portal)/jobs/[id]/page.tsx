import { Building2, CalendarDays, MapPin, ShieldQuestion } from "lucide-react";
import { apiGet } from "@/lib/server-api";
import type { Job } from "@/lib/types";
import { ExternalApplyLink } from "@/components/external-apply-link";

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; const job = await apiGet<Job>(`/api/v1/jobs/${id}`);
  if (!job) return <div className="shell py-20"><h1 className="text-5xl">This dossier is unavailable.</h1></div>;
  return (
    <div className="shell py-12"><div className="editorial-grid">
      <article className="paper-card p-7 sm:p-10"><p className="eyebrow">Job dossier · {job.source}</p><h1 className="text-[clamp(3.2rem,7vw,6rem)] leading-[.94] mt-4">{job.title}</h1><div className="flex flex-wrap gap-5 text-muted my-6"><span className="flex gap-2"><Building2 size={17} />{job.company}</span><span className="flex gap-2"><MapPin size={17} />{job.location || "Not stated"}</span>{job.posted_at && <span className="flex gap-2"><CalendarDays size={17} />{job.posted_at}</span>}</div><div className="rule pt-8 whitespace-pre-line leading-relaxed text-[#38342f]">{job.description}</div></article>
      <aside className="space-y-4"><div className="paper-card p-6"><p className="eyebrow">Evidence check</p><h2 className="text-3xl mt-2">Before you invest.</h2><div className="mt-6 space-y-4">{job.skills?.slice(0, 6).map((skill) => <div key={skill} className="flex justify-between border-b border-black/10 pb-2"><span>{skill}</span><span className="text-affirm">stated</span></div>)}<p className="flex gap-2 text-sm text-muted"><ShieldQuestion size={17} /> Sponsorship: {job.opt_cpt_flag == null ? "not stated" : job.opt_cpt_flag ? "positive signal" : "restriction stated"}</p></div></div><ExternalApplyLink jobId={job.id} href={job.apply_url || job.source_url} /><p className="text-xs text-muted">HOPE opens the original application. It never submits on your behalf.</p></aside>
    </div></div>
  );
}
