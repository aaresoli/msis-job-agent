"use client";

import { ArrowUpRight } from "lucide-react";

import { browserApi, csrfToken } from "@/lib/api";

export function ExternalApplyLink({ jobId, href }: { jobId: string; href?: string }) {
  if (!href) return null;
  return (
    <a
      className="button-primary w-full"
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={() => {
        void browserApi(`/api/v1/jobs/${jobId}/feedback`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken(),
          },
          body: JSON.stringify({ action: "opened" }),
        });
      }}
    >
      Apply on source <ArrowUpRight size={16} />
    </a>
  );
}
