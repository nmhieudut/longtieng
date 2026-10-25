"use client";

import { AlertTriangle, Clapperboard, Download, FileJson, FileText, Loader2, Play, RotateCcw, Subtitles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { fileUrl, fmt, isActive, type Project } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  project: Project;
  previewAt: number;
  onPreview: () => void;
  onRender: () => void;
  onRetry: () => void;
};

export function StatusPanel({ project: p, previewAt, onPreview, onRender, onRetry }: Props) {
  const s = p.status;
  const active = isActive(p);
  const ready = p.segments.length > 0;
  const o = p.outputs;
  const counts = { ok: 0, fast: 0, overflow: 0, empty: 0 };
  for (const seg of p.segments) {
    if (!seg.vi.trim()) counts.empty++;
    else counts[seg.fit?.status ?? "ok"]++;
  }

  const dl = (key: keyof Project["outputs"]) => {
    const f = o[key];
    return f ? `${fileUrl(p.id, f.file)}?download=1&t=${f.at ?? ""}` : undefined;
  };

  return (
    <Card>
      <CardContent className="grid gap-4">
        <div className="flex items-start gap-3">
          <span className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-full",
            s.stage === "error" ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary")}>
            {active ? <Loader2 className="size-4 animate-spin" /> : s.stage === "error" ? <AlertTriangle className="size-4" /> : <Clapperboard className="size-4" />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-medium">{s.message}</p>
            {ready && (
              <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{p.segments.length} câu</span>
                <span className="text-ok">● {counts.ok} vừa</span>
                {counts.fast > 0 && <span className="text-fast-foreground">● {counts.fast} đọc nhanh</span>}
                {counts.overflow > 0 && <span className="font-medium text-over">● {counts.overflow} tràn</span>}
                {counts.empty > 0 && <span>● {counts.empty} chưa dịch</span>}
              </p>
            )}
          </div>
        </div>

        {active && (
          <div className="grid gap-1">
            {s.progress != null ? (
              <Progress value={s.progress * 100} />
            ) : (
              <div className="relative h-2 overflow-hidden rounded-full bg-primary/20">
                <div className="absolute inset-y-0 w-1/3 animate-[indet_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
              </div>
            )}
            {s.progress != null && <span className="text-right font-mono text-xs text-muted-foreground">{Math.round(s.progress * 100)}%</span>}
          </div>
        )}

        {s.error && (
          <Alert variant="destructive">
            <AlertTriangle />
            <AlertTitle>Có lỗi</AlertTitle>
            <AlertDescription className="whitespace-pre-wrap break-words font-mono text-xs">{s.error}</AlertDescription>
          </Alert>
        )}

        {p.warnings.length > 0 && (
          <Alert>
            <AlertTriangle className="text-fast-foreground" />
            <AlertTitle>Lưu ý</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            </AlertDescription>
          </Alert>
        )}

        {s.stage === "error" && !ready && (
          <Button variant="outline" onClick={onRetry} disabled={active}><RotateCcw /> Thử lại</Button>
        )}

        {ready && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Button variant="outline" size="lg" className="h-10" disabled={active} onClick={onPreview}>
              <Play /> Xem thử 30s từ {fmt(previewAt)}
            </Button>
            <Button size="lg" className="h-10" disabled={active} onClick={onRender}>
              <Clapperboard /> Lồng tiếng & xuất video
            </Button>
          </div>
        )}

        {o.srt && (
          <>
            <Separator />
            <div className="flex flex-wrap gap-2">
              {o.final && (
                <Button asChild size="sm"><a href={dl("final")}><Download /> Video MP4</a></Button>
              )}
              <Button asChild size="sm" variant="outline"><a href={dl("srt")}><Subtitles /> Phụ đề .srt</a></Button>
              <Button asChild size="sm" variant="outline"><a href={dl("json")}><FileJson /> .json</a></Button>
              <Button asChild size="sm" variant="outline"><a href={dl("txt")}><FileText /> .txt</a></Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
