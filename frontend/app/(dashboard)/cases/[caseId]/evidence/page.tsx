"use client";

import { EvidenceSection } from "@/components/evidence/evidence-section";
import { useCaseContext } from "@/components/cases/case-shell";

export default function CaseEvidencePage() {
  const { caseItem } = useCaseContext();
  return <EvidenceSection caseId={caseItem.id} />;
}
