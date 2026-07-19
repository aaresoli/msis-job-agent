import { Bell } from "lucide-react";
import { apiGet } from "@/lib/server-api";

type Notification = { id: string; title: string; body: string; created_at: string };
export default async function NotificationsPage() { const items = await apiGet<Notification[]>("/api/v1/me/notifications") ?? []; return <div className="shell py-12 max-w-4xl"><p className="eyebrow">Notification desk</p><h1 className="text-6xl mt-2">What changed.</h1><div className="space-y-3 mt-8">{items.map((item) => <article className="paper-card p-5 flex gap-4" key={item.id}><Bell size={18} className="text-[#7a170f] shrink-0" /><div><h2 className="font-semibold">{item.title}</h2><p className="text-[#686258]">{item.body}</p></div></article>)}{!items.length && <div className="paper-card p-8"><h2 className="text-3xl">You’re caught up.</h2></div>}</div></div>; }
