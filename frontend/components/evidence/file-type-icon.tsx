import {
  AudioLines,
  Clapperboard,
  File,
  FileSpreadsheet,
  FileText,
  Image as ImageIcon,
  Mail,
} from "lucide-react";
import type { EvidenceType } from "@/lib/types/evidence";

export function FileTypeIcon({
  type,
  className = "h-5 w-5",
}: {
  type: EvidenceType | string;
  className?: string;
}) {
  switch (type) {
    case "document":
      return <FileText className={className} aria-hidden />;
    case "image":
      return <ImageIcon className={className} aria-hidden />;
    case "audio":
      return <AudioLines className={className} aria-hidden />;
    case "tabular":
      return <FileSpreadsheet className={className} aria-hidden />;
    case "email":
      return <Mail className={className} aria-hidden />;
    case "video":
      return <Clapperboard className={className} aria-hidden />;
    default:
      return <File className={className} aria-hidden />;
  }
}
