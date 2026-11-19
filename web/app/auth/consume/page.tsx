import { Suspense } from "react";

import { ConsumeMagicLink } from "./consume-magic-link";

export default function ConsumePage() {
  return (
    <main className="grid min-h-screen place-items-center px-6">
      <Suspense fallback={<p className="display text-3xl">Opening your career desk…</p>}>
        <ConsumeMagicLink />
      </Suspense>
    </main>
  );
}
