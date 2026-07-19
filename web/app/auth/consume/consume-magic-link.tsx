"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { browserApi } from "@/lib/api";

export function ConsumeMagicLink() {
  const params = useSearchParams();
  const token = params.get("token");
  const router = useRouter();
  const [message, setMessage] = useState(
    token ? "Opening your career desk…" : "This sign-in link is incomplete.",
  );

  useEffect(() => {
    if (!token) return;

    browserApi("/api/v1/auth/magic-link/consume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Magic link was rejected");
        const data = (await response.json()) as { csrf_token: string };
        window.sessionStorage.setItem("hope_csrf", data.csrf_token);
        router.replace("/today");
      })
      .catch(() =>
        setMessage("This link is invalid or expired. Request a new one."),
      );
  }, [router, token]);

  return <p className="display text-3xl">{message}</p>;
}
