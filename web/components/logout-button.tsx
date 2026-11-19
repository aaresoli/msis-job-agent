"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";

import { browserApi, csrfToken } from "@/lib/api";

export function LogoutButton() {
  const router = useRouter();
  return (
    <button
      className="p-2"
      aria-label="Sign out"
      onClick={async () => {
        const response = await browserApi("/api/v1/auth/logout", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
        });
        if (response.ok) {
          window.sessionStorage.removeItem("hope_csrf");
          router.replace("/auth/login");
        }
      }}
    >
      <LogOut size={19} />
    </button>
  );
}
