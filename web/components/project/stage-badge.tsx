import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ACTIVE, STAGE_LABEL, type Stage } from "@/lib/api";

export function StageBadge({ stage, hasFinal, progress }: { stage: Stage; hasFinal?: boolean; progress?: number | null }) {
  if (stage === "error") {
    return <Badge variant="destructive"><XCircle /> Lỗi</Badge>;
  }
  if (ACTIVE.has(stage)) {
    return (
      <Badge variant="secondary" className="tabular-nums">
        <Loader2 className="animate-spin" />
        {STAGE_LABEL[stage]}{progress != null && progress > 0 ? ` ${Math.round(progress * 100)}%` : ""}
      </Badge>
    );
  }
  if (hasFinal || stage === "done") {
    return <Badge className="bg-ok/15 text-ok"><CheckCircle2 /> Có video</Badge>;
  }
  return <Badge variant="outline">{STAGE_LABEL[stage]}</Badge>;
}
