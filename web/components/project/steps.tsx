import { Check, Loader2, X } from "lucide-react";

import { isActive, type Project } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEPS = ["Nhận dạng & dịch", "Duyệt & chỉnh câu", "Lồng tiếng & xuất"];

function current(p: Project): { idx: number; state: "active" | "wait" | "error" | "done" } {
  const st = p.status.stage;
  if (st === "new") return { idx: 0, state: "wait" };
  if (st === "error") return { idx: p.segments.length ? 1 : 0, state: "error" };
  if (st === "done") return { idx: 3, state: "done" };
  if (["dubbing", "separating", "rendering"].includes(st)) return { idx: 2, state: "active" };
  if (p.segments.length) return { idx: 1, state: isActive(p) ? "active" : "wait" };
  return { idx: 0, state: "active" };
}

export function Steps({ project }: { project: Project }) {
  const { idx, state } = current(project);
  return (
    <ol className="flex items-center gap-2 text-sm">
      {STEPS.map((label, i) => {
        const done = i < idx;
        const here = i === idx;
        return (
          <li key={label} className="flex min-w-0 items-center gap-2">
            {i > 0 && <span className={cn("h-px w-4 shrink-0 sm:w-8", done || here ? "bg-primary" : "bg-border")} />}
            <span
              className={cn(
                "grid size-6 shrink-0 place-items-center rounded-full border text-xs font-semibold",
                done && "border-primary bg-primary text-primary-foreground",
                here && state === "error" && "border-destructive bg-destructive text-white",
                here && state !== "error" && "border-primary text-primary",
              )}
            >
              {done ? <Check className="size-3.5" /> : here && state === "error" ? <X className="size-3.5" />
                : here && state === "active" ? <Loader2 className="size-3.5 animate-spin" /> : i + 1}
            </span>
            <span className={cn("hidden truncate md:inline", here ? "font-medium" : "text-muted-foreground")}>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
