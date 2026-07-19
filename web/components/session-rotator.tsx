"use client";

import { useEffect } from "react";

import { browserApi, csrfToken } from "@/lib/api";

export function SessionRotator() {
  useEffect(() => {
    const currentCsrf = csrfToken();
    if (!currentCsrf) return;
    void browserApi("/api/v1/auth/session/rotate", {
      method: "POST",
      headers: { "X-CSRF-Token": currentCsrf },
    }).then(async (response) => {
      if (!response.ok) return;
      const data = (await response.json()) as { csrf_token?: string };
      if (data.csrf_token)
        window.sessionStorage.setItem("hope_csrf", data.csrf_token);
    });
  }, []);
  return null;
}
