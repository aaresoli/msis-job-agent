import "server-only";

import { cookies } from "next/headers";

const internalBase = process.env.HOPE_API_INTERNAL_URL ?? "http://app:8000";

export async function apiGet<T>(path: string): Promise<T | null> {
  const cookieStore = await cookies();
  try {
    const response = await fetch(`${internalBase}${path}`, {
      headers: { cookie: cookieStore.toString() },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}
