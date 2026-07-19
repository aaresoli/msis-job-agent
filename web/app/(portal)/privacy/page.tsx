"use client";

import { Download, LockKeyhole, ShieldCheck, Trash2, UserRoundX } from "lucide-react";
import { useEffect, useState } from "react";

import { browserApi, csrfToken } from "@/lib/api";

type Consent = {
  id: string;
  policy_version: string;
  ai_matching: boolean;
  accepted_at: string;
};

type Grant = {
  id: string;
  advisor: string;
  scope: string[];
  expires_at: string;
  revoked_at?: string;
};

export default function PrivacyPage() {
  const [consents, setConsents] = useState<Consent[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [status, setStatus] = useState("");

  async function refresh() {
    const [consentResponse, grantResponse] = await Promise.all([
      browserApi("/api/v1/me/consents"),
      browserApi("/api/v1/me/sharing-grants"),
    ]);
    if (consentResponse.ok) setConsents((await consentResponse.json()) as Consent[]);
    if (grantResponse.ok) setGrants((await grantResponse.json()) as Grant[]);
  }

  useEffect(() => {
    void Promise.all([
      browserApi("/api/v1/me/consents"),
      browserApi("/api/v1/me/sharing-grants"),
    ]).then(async ([consentResponse, grantResponse]) => {
      if (consentResponse.ok)
        setConsents((await consentResponse.json()) as Consent[]);
      if (grantResponse.ok) setGrants((await grantResponse.json()) as Grant[]);
    });
  }, []);

  async function recordConsent(aiMatching: boolean) {
    const response = await browserApi("/api/v1/me/consents", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify({ policy_version: "pilot-v1", ai_matching: aiMatching }),
    });
    setStatus(response.ok ? "Your consent choice was recorded." : "Consent could not be updated.");
    if (response.ok) await refresh();
  }

  async function revoke(grantId: string) {
    const response = await browserApi(`/api/v1/me/sharing-grants/${grantId}`, {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    setStatus(response.ok ? "Advisor access was revoked." : "Access could not be revoked.");
    if (response.ok) await refresh();
  }

  async function requestDeletion() {
    if (!window.confirm("Queue deletion of your private HOPE data? This cannot be undone.")) return;
    const response = await browserApi("/api/v1/me/deletion", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() },
    });
    setStatus(response.ok ? "Deletion is queued for the nightly privacy run." : "Deletion could not be queued.");
  }

  return (
    <div className="shell py-12 max-w-6xl">
      <p className="eyebrow">Privacy center</p>
      <h1 className="text-[clamp(3.2rem,7vw,6rem)] mt-3">Your evidence. Your permission.</h1>
      <p className="text-xl text-[#686258] max-w-2xl mt-4">Individual data stays private on the DGX. GCS receives suppressed cohort aggregates unless you grant a named advisor access.</p>
      <div className="grid lg:grid-cols-2 gap-6 mt-10">
        <section className="paper-card p-7">
          <ShieldCheck className="text-[#7a170f]" />
          <h2 className="text-3xl mt-4">AI matching consent</h2>
          <p className="mt-3 text-[#686258]">HOPE uses local inference to rank and explain. It never applies or sends messages.</p>
          <div className="flex flex-wrap gap-3 mt-6"><button className="button-primary" onClick={() => recordConsent(true)}>Allow local matching</button><button className="button-quiet" onClick={() => recordConsent(false)}>Pause matching</button></div>
          <div className="rule mt-7 pt-4 space-y-2 text-sm">{consents.slice(0, 4).map((consent) => <p key={consent.id}>{consent.policy_version} · {consent.ai_matching ? "allowed" : "paused"} · {new Date(consent.accepted_at).toLocaleDateString()}</p>)}</div>
        </section>
        <section className="paper-card p-7">
          <LockKeyhole className="text-[#7a170f]" />
          <h2 className="text-3xl mt-4">Advisor sharing</h2>
          {!grants.length && <p className="mt-3 text-[#686258]">No advisor can view your individual profile or applications.</p>}
          <div className="mt-5 space-y-4">{grants.map((grant) => <div className="border-b border-black/10 pb-4" key={grant.id}><p className="font-semibold">{grant.advisor}</p><p className="text-sm text-[#686258]">{grant.scope.join(", ")} · expires {new Date(grant.expires_at).toLocaleDateString()}</p>{!grant.revoked_at && <button className="mt-2 text-sm font-semibold text-[#7a170f]" onClick={() => revoke(grant.id)}>Revoke access</button>}</div>)}</div>
        </section>
        <section className="paper-card p-7">
          <Download className="text-[#7a170f]" />
          <h2 className="text-3xl mt-4">Take a copy</h2>
          <p className="my-4 text-[#686258]">Export your account, profile, and consent history as JSON.</p>
          <a className="button-quiet inline-flex gap-2" href="/api/v1/me/export" download><Download size={16} /> Export my data</a>
        </section>
        <section className="paper-card p-7 border-[#7a170f]/40">
          <UserRoundX className="text-[#7a170f]" />
          <h2 className="text-3xl mt-4">Leave HOPE</h2>
          <p className="my-4 text-[#686258]">Queue deletion of resumes, conversations, applications, profile data, and workflow checkpoints.</p>
          <button className="button-quiet inline-flex gap-2" onClick={requestDeletion}><Trash2 size={16} /> Request deletion</button>
        </section>
      </div>
      {status && <p role="status" className="mt-6 bg-[#b9c8a2]/40 p-4">{status}</p>}
    </div>
  );
}
