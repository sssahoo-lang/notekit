import { Suspense } from "react";

import { ResetForm } from "@/components/reset-form";

export const metadata = { title: "Choose a new password · NoteKit" };

// useSearchParams needs a boundary, or the whole route opts out of static
// rendering at build time.
export default function Page() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
