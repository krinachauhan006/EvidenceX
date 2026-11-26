"use client";

import { Suspense } from "react";
import { useParams } from "next/navigation";
import { EvidenceWorkspace } from "@/components/workspace/evidence-workspace";
import { LoadingState } from "@/components/ui/primitives";

export default function EvidenceWorkspacePage() {
  const params = useParams<{ evidenceId: string }>();
  return (
    <Suspense fallback={<LoadingState label="Opening evidence workspace…" />}>
      <EvidenceWorkspace evidenceId={params.evidenceId} />
    </Suspense>
  );
}
