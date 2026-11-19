"use client";

import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { browserApi, csrfToken } from "@/lib/api";
import type { Application } from "@/lib/types";

const columns = ["saved", "preparing", "applied", "interview", "offer"];
export default function ApplicationsPage() {
  const [items, setItems] = useState<Application[]>([]);
  const [showForm, setShowForm] = useState(false);
  useEffect(() => { browserApi("/api/v1/applications").then((r) => r.ok ? r.json() : []).then(setItems); }, []);
  async function add(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const response = await browserApi("/api/v1/applications", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() }, body: JSON.stringify({ company_name: form.get("company"), role_title: form.get("role"), status: "saved" }) });
    if (response.ok) {
      const created = (await response.json()) as Application;
      setItems((current) => [created, ...current]);
    }
    setShowForm(false);
  }
  return <div className="shell py-12"><div className="flex justify-between items-end gap-4"><div><p className="eyebrow">My search</p><h1 className="text-6xl mt-2">Momentum, made visible.</h1></div><button className="button-primary" onClick={() => setShowForm(!showForm)}><Plus size={16} /> Add application</button></div>
    {showForm && <form onSubmit={add} className="paper-card p-5 my-6 grid sm:grid-cols-[1fr_1fr_auto] gap-3"><input name="company" required placeholder="Company" className="border border-black/20 p-3 bg-white/60" /><input name="role" required placeholder="Role title" className="border border-black/20 p-3 bg-white/60" /><button className="button-primary">Save</button></form>}
    <div className="grid xl:grid-cols-5 md:grid-cols-3 gap-4 mt-10 overflow-x-auto">{columns.map((column) => <section key={column} className="min-w-[220px]"><h2 className="eyebrow border-b border-black/20 pb-3">{column} · {items.filter((item) => item.status === column).length}</h2><div className="space-y-3 mt-3">{items.filter((item) => item.status === column).map((item) => <article className="paper-card p-4" key={item.id}><h3 className="text-xl">{item.role_title}</h3><p className="text-sm text-muted">{item.company_name}</p>{item.deadline && <p className="text-xs mt-3">Due {item.deadline}</p>}</article>)}</div></section>)}</div>
  </div>;
}
