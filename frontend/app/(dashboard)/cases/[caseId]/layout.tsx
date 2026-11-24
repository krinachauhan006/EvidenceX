import { CaseShell } from "@/components/cases/case-shell";

export default function CaseLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { caseId: string };
}) {
  return <CaseShell caseId={params.caseId}>{children}</CaseShell>;
}
