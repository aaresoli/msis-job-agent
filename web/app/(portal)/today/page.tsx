import { ArrowRight, Radar } from "lucide-react";
import Link from "next/link";
import { JobCard } from "@/components/job-card";
import { apiGet } from "@/lib/server-api";
import type { Match } from "@/lib/types";

export default async function TodayPage() {
  const data = await apiGet<{ items: Match[]; needs_profile: boolean }>("/api/v1/matches");
  const matches = data?.items ?? [];
  return (
    <div className="shell py-10 sm:py-16">
      <div className="editorial-grid">
        <section>
          <p className="eyebrow">Tuesday briefing</p>
          <h1 className="text-[clamp(3.5rem,7vw,6.8rem)] leading-[.9] mt-3">Good work is<br /><span className="italic text-[#7a170f]">coming into view.</span></h1>
          <p className="text-lg text-[#686258] mt-6 mb-10 max-w-2xl">Your strongest current opportunities, ordered by evidence—not hype.</p>
          <div className="space-y-5">
            {matches.map((match, index) => <JobCard key={match.match_id} match={match} index={index} />)}
            {!matches.length && <div className="paper-card p-10 text-center"><Radar className="mx-auto text-[#7a170f]" /><h2 className="text-3xl mt-4">Your briefing is being assembled.</h2><p className="text-[#686258] mt-2 mb-6">Complete your profile, or explore the live job library while matching runs.</p><Link href={data?.needs_profile ? "/profile" : "/explore"} className="button-primary">Continue <ArrowRight size={16} /></Link></div>}
          </div>
        </section>
        <aside className="space-y-5">
          <div className="paper-card p-6 sticky top-28"><p className="eyebrow">This week</p><p className="display text-5xl mt-3">03</p><p className="text-[#686258]">new high-confidence matches</p><div className="rule mt-5 pt-5"><p className="font-semibold">One useful move</p><p className="text-sm text-[#686258] mt-1">Review unknown sponsorship language before investing in a tailored application.</p></div><Link href="/market-pulse" className="mt-6 flex items-center gap-2 font-semibold">Read Market Pulse <ArrowRight size={15} /></Link></div>
        </aside>
      </div>
    </div>
  );
}
