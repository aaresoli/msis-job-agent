"use client";

import { FormEvent, useEffect, useState } from "react";
import { Check, LockKeyhole, Upload } from "lucide-react";
import Link from "next/link";
import { browserApi, csrfToken } from "@/lib/api";

type StudentProfile = {
  name?: string;
  concentration?: string;
  academic_stage?: string;
  remote_preference?: string;
  target_roles?: string[];
  skills?: string[];
  work_auth_status?: string;
};

export default function ProfilePage() {
  const [profile, setProfile] = useState<StudentProfile>({}); const [status, setStatus] = useState("");
  useEffect(() => {
    browserApi("/api/v1/me/profile")
      .then((response) =>
        response.ok
          ? (response.json() as Promise<{ profile?: StudentProfile }>)
          : {},
      )
      .then((data) =>
        setProfile((data as { profile?: StudentProfile }).profile ?? {}),
      );
  }, []);
  async function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const payload = { name: form.get("name"), concentration: form.get("concentration"), academic_stage: form.get("stage"), target_roles: String(form.get("roles") || "").split(",").map((v) => v.trim()).filter(Boolean), skills: String(form.get("skills") || "").split(",").map((v) => v.trim()).filter(Boolean), work_auth_status: form.get("work_auth") || null, geo_preference: [], remote_preference: form.get("remote") || null, match_frequency: "Once a day" }; const response = await browserApi("/api/v1/me/profile", { method: "PUT", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() }, body: JSON.stringify(payload) }); setStatus(response.ok ? "Profile saved" : "Could not save profile"); }
  async function upload(event: React.ChangeEvent<HTMLInputElement>) { const file = event.target.files?.[0]; if (!file) return; const body = new FormData(); body.append("file", file); const response = await browserApi("/api/v1/me/resume", { method: "POST", headers: { "X-CSRF-Token": csrfToken() }, body }); setStatus(response.ok ? "Resume securely uploaded for local parsing" : "Resume upload failed"); }
  return <div className="shell py-12"><div className="editorial-grid"><section><p className="eyebrow">Profile and preferences</p><h1 className="text-6xl mt-2">Give the matcher better evidence.</h1><form onSubmit={save} className="paper-card p-7 mt-8 grid sm:grid-cols-2 gap-5"><label className="space-y-2"><span className="font-semibold">Name</span><input name="name" required defaultValue={profile.name} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2"><span className="font-semibold">Concentration</span><input name="concentration" required defaultValue={profile.concentration} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2"><span className="font-semibold">Academic stage</span><input name="stage" defaultValue={profile.academic_stage} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2"><span className="font-semibold">Remote preference</span><input name="remote" defaultValue={profile.remote_preference} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2 sm:col-span-2"><span className="font-semibold">Target roles <small className="font-normal text-[#686258]">comma-separated</small></span><input name="roles" defaultValue={(profile.target_roles || []).join(", ")} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2 sm:col-span-2"><span className="font-semibold">Skills</span><textarea name="skills" defaultValue={(profile.skills || []).join(", ")} className="w-full border border-black/20 bg-white/60 p-3" /></label><label className="space-y-2 sm:col-span-2"><span className="font-semibold">Work authorization context</span><input name="work_auth" defaultValue={profile.work_auth_status} className="w-full border border-black/20 bg-white/60 p-3" /></label><button className="button-primary sm:col-span-2"><Check size={16} /> Save profile</button></form></section><aside className="space-y-5"><div className="paper-card p-6"><Upload className="text-[#7a170f]" /><h2 className="text-3xl mt-4">Resume evidence</h2><p className="text-sm text-[#686258] mt-2 mb-5">PDF or DOCX, up to 10 MB. Parsing stays on your private stack and waits for your confirmation.</p><label className="button-quiet inline-block cursor-pointer">Choose resume<input type="file" accept=".pdf,.docx" className="sr-only" onChange={upload} /></label></div><div className="paper-card p-6"><LockKeyhole className="text-[#7a170f]" /><h2 className="text-2xl mt-3">You control access.</h2><p className="text-sm text-[#686258] mt-2">GCS sees cohort trends. Your individual profile, applications, resume, and coach remain private unless you grant an advisor access.</p><Link href="/privacy" className="font-semibold text-[#7a170f] inline-block mt-4">Open privacy center →</Link></div>{status && <p role="status" className="bg-[#b9c8a2]/40 p-4">{status}</p>}</aside></div></div>;
}
