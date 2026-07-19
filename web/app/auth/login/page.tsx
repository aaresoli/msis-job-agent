"use client";

import { useState } from "react";
import Link from "next/link";
import { browserApi } from "@/lib/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true);
    try {
      const response = await browserApi("/api/v1/auth/magic-link/request", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }),
      });
      const data = await response.json(); setMessage(data.message ?? "Check your email.");
    } catch { setMessage("The sign-in service is unavailable. Please try again shortly."); }
    finally { setBusy(false); }
  }
  return (
    <main className="min-h-screen grid place-items-center p-5">
      <section className="paper-card w-full max-w-xl p-8 sm:p-12 reveal">
        <Link href="/" className="display text-2xl">HOPE.</Link>
        <p className="eyebrow mt-16">Private student access</p>
        <h1 className="text-5xl mt-3 mb-4">Return to your career desk.</h1>
        <p className="text-[#686258] mb-8">We’ll email a one-time link to your invited address. No password to remember.</p>
        <form onSubmit={submit} className="space-y-4">
          <label className="block font-semibold" htmlFor="email">University email</label>
          <input id="email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)}
            className="w-full bg-white/60 border border-black/25 px-4 py-3" placeholder="name@iu.edu" />
          <button className="button-primary w-full" disabled={busy}>{busy ? "Sending…" : "Email my sign-in link"}</button>
        </form>
        {message && <p role="status" className="mt-5 p-4 bg-[#b9c8a2]/35">{message}</p>}
      </section>
    </main>
  );
}
