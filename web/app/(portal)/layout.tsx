import { Nav } from "@/components/nav";
import { SessionRotator } from "@/components/session-rotator";
import { apiGet } from "@/lib/server-api";
import { redirect } from "next/navigation";

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const session = await apiGet<{ user_id: string }>("/api/v1/auth/session");
  if (!session) redirect("/auth/login");
  return <><SessionRotator /><Nav /><main>{children}</main></>;
}
