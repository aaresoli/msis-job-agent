import { ArrowUpRight, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden">
      <div className="shell py-7 flex items-center justify-between">
        <div className="display text-3xl">HOPE<span className="text-crimson">.</span></div>
        <Link href="/auth/login" className="button-quiet">Student sign in</Link>
      </div>
      <section className="shell min-h-[78vh] grid lg:grid-cols-[1.15fr_.85fr] items-center gap-14 py-16">
        <div className="reveal">
          <p className="eyebrow">Kelley MSIS · Career intelligence</p>
          <h1 className="text-[clamp(4rem,9vw,8.7rem)] leading-[.82] mt-6 mb-8">
            Your search,<br /><span className="text-crimson italic">in focus.</span>
          </h1>
          <p className="text-xl text-ink-soft max-w-2xl leading-relaxed">
            A private career desk that turns thousands of opportunities into a short,
            evidence-led plan built around your skills, ambitions, and work authorization.
          </p>
          <div className="flex flex-wrap gap-3 mt-10">
            <Link href="/auth/login" className="button-primary">Open your desk <ArrowUpRight size={17} /></Link>
            <span className="flex items-center gap-2 px-4 text-sm text-muted"><ShieldCheck size={17} /> Local AI. Student controlled.</span>
          </div>
        </div>
        <div className="relative reveal" style={{ animationDelay: "140ms" }}>
          <div className="absolute -inset-10 bg-sage/35 rounded-full blur-3xl" />
          <div className="paper-card relative p-7 rotate-[1.5deg]">
            <div className="flex justify-between items-start border-b border-black/15 pb-5">
              <div><p className="eyebrow">Today’s strongest signal</p><h2 className="text-3xl mt-2">Data Strategy Analyst</h2><p className="text-muted">Eli Lilly · Indianapolis</p></div>
              <div className="score-ring" style={{ "--score": "91%" } as React.CSSProperties}><span>91</span></div>
            </div>
            <div className="py-6 space-y-3 text-sm">
              <p><strong>Why it rose:</strong> your SQL, Tableau, and healthcare analytics experience align with three stated requirements.</p>
              <p><strong>Watch:</strong> sponsorship language is not stated. HOPE marks it unknown instead of guessing.</p>
            </div>
            <div className="flex gap-2"><span className="tag">SQL</span><span className="tag">Tableau</span><span className="tag">Healthcare</span></div>
          </div>
          <div className="paper-card absolute -bottom-16 -left-10 p-4 w-56 -rotate-3 hidden sm:block">
            <Sparkles size={17} className="text-crimson mb-3" />
            <p className="text-sm"><strong>Market pulse</strong><br />Analytics hiring mentions rose across three tracked employers this week.</p>
          </div>
        </div>
      </section>
    </main>
  );
}
