"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowUp, Bot, Sparkles } from "lucide-react";
import { browserApi, csrfToken } from "@/lib/api";

type Message = { role: string; content: string };
export default function CoachPage() {
  const [thread, setThread] = useState<string>(); const [messages, setMessages] = useState<Message[]>([]); const [question, setQuestion] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { browserApi("/api/v1/coach/threads").then((r) => r.ok ? r.json() : []).then(async (rows) => { if (rows[0]) setThread(rows[0].id); else { const created = await browserApi("/api/v1/coach/threads", { method: "POST", headers: { "X-CSRF-Token": csrfToken() } }); if (created.ok) setThread((await created.json()).id); } }); }, []);
  async function send(event: FormEvent) {
    event.preventDefault(); if (!thread || !question.trim()) return; const prompt = question; setQuestion(""); setBusy(true); setMessages((m) => [...m, { role: "user", content: prompt }, { role: "assistant", content: "" }]);
    const response = await browserApi(`/api/v1/coach/threads/${thread}/messages`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() }, body: JSON.stringify({ content: prompt }) });
    if (!response.body) { setBusy(false); return; } const reader = response.body.getReader(); const decoder = new TextDecoder();
    while (true) { const { value, done } = await reader.read(); if (done) break; const text = decoder.decode(value); for (const block of text.split("\n\n")) { if (!block.includes("event: token")) continue; const line = block.split("\n").find((part) => part.startsWith("data: ")); if (!line) continue; try { const chunk = JSON.parse(line.slice(6)).text; setMessages((current) => current.map((message, index) => index === current.length - 1 ? { ...message, content: message.content + chunk } : message)); } catch {} } }
    setBusy(false);
  }
  return <div className="shell py-10 max-w-5xl"><div className="grid md:grid-cols-[250px_1fr] gap-6"><aside className="paper-card p-5 h-fit"><Sparkles className="text-crimson" /><h1 className="text-3xl mt-4">Career coach</h1><p className="text-sm text-muted mt-3">Private, local, and advisory. HOPE can help you reason—it cannot apply or contact anyone.</p><div className="rule mt-5 pt-4 text-xs text-muted">Responses may be imperfect. Verify employer requirements at the source.</div></aside><section className="paper-card min-h-[70vh] flex flex-col"><div className="p-5 border-b border-black/10 flex items-center gap-3"><Bot size={20} /><div><p className="font-semibold">HOPE local coach</p><p className="text-xs text-muted">Student-controlled session</p></div></div><div className="flex-1 p-5 sm:p-8 space-y-5">{!messages.length && <div className="max-w-lg"><p className="eyebrow">A useful place to begin</p><h2 className="text-4xl mt-2">What should we make clearer today?</h2><p className="text-muted mt-3">Compare two roles, plan this week’s applications, or inspect a skills gap.</p></div>}{messages.map((message, index) => <div key={index} className={message.role === "user" ? "ml-auto bg-crimson text-white p-4 max-w-[80%]" : "max-w-[86%] leading-relaxed"}>{message.content || (busy ? "Thinking locally…" : "")}</div>)}</div><form onSubmit={send} className="border-t border-black/10 p-4 flex gap-3"><label className="sr-only" htmlFor="question">Message your career coach</label><textarea id="question" value={question} onChange={(e) => setQuestion(e.target.value)} className="flex-1 border border-black/20 bg-white/60 p-3 resize-none" rows={2} placeholder="Ask about your search…" /><button aria-label="Send" disabled={busy} className="button-primary self-end"><ArrowUp size={17} /></button></form></section></div></div>;
}
