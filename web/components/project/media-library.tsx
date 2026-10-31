"use client";

import { Film, Layers, Plus, RotateCw, Trash2, Upload } from "lucide-react";
import { type RefObject, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { api, fileUrl, isActive, type Project } from "@/lib/api";
import { clock } from "@/lib/timeline";
import { cn } from "@/lib/utils";

import type { TimelineHandle } from "./timeline-panel";

type Film = NonNullable<Project["film"]>;

/** Every video of the project. Drag one onto the timeline to put it between two clips, onto the picture row to
 *  lay it over the video, or drop files from the computer straight onto the timeline. */
export function MediaLibrary({ project: p, tl, onApply, disabled }: {
  project: Project; tl: RefObject<TimelineHandle | null>; onApply: (p: Project) => void; disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [confirm, setConfirm] = useState<number | null>(null);
  const items: { id: number; name: string; duration: number; film?: Film; has_audio: boolean }[] = [
    { id: 0, name: p.title, duration: p.media?.duration ?? 0, film: p.film, has_audio: true },
    ...(p.extra_sources ?? []).map((e) => ({ id: e.id, name: e.name, duration: e.duration, film: e.film, has_audio: e.has_audio })),
  ];
  const uses = (id: number) => (p.timeline?.clips ?? (id === 0 ? [{ src: 0 }] : [])).filter((c) => (c.src ?? 0) === id).length
    + (p.overlays ?? []).filter((o) => o.kind === "video" && (o.src ?? 0) === id).length;

  return (
    <div className="grid content-start gap-3 p-3"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setOver(true); } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); tl.current?.uploadFiles(Array.from(e.dataTransfer.files)); }}>
      <button type="button" disabled={disabled} onClick={() => input.current?.click()}
        className={cn("flex flex-col items-center gap-1.5 rounded-xl border-[1.5px] border-dashed border-input bg-muted/40 px-3 py-5 text-center text-sm transition-colors disabled:opacity-60",
          over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-accent")}>
        <Upload className="size-5 text-primary" />
        <span className="font-medium">Thêm video (chọn nhiều file được)</span>
        <span className="text-xs text-muted-foreground">hoặc kéo file vào đây, hay thả thẳng lên timeline</span>
      </button>
      <input ref={input} type="file" hidden multiple accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv,.m4v"
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); e.target.value = ""; if (fs.length) tl.current?.uploadFiles(fs); }} />
      <p className="text-xs text-muted-foreground">Kéo một video xuống timeline để chèn vào giữa hai đoạn, hoặc thả vào hàng chữ/hình dán để chồng lên video.</p>
      <ul className="grid gap-2">
        {items.map((it) => (
          <li key={it.id} draggable={!disabled && it.duration > 0}
            onDragStart={(e) => { e.dataTransfer.setData("text/lt-src", String(it.id)); e.dataTransfer.effectAllowed = "copy"; }}
            className="flex cursor-grab items-center gap-2.5 rounded-xl border bg-card p-2 active:cursor-grabbing">
            <span className="relative grid h-14 w-10 shrink-0 place-items-center overflow-hidden rounded-lg bg-secondary text-muted-foreground"
              style={it.film ? { backgroundImage: `url(${fileUrl(p.id, it.film.file)})`, backgroundSize: `${it.film.n * 100}% 100%`, backgroundPosition: "0 0" } : undefined}>
              {!it.film && <Film className="size-4" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium" title={it.name}>{it.id === 0 ? `Video chính · ${it.name}` : it.name}</span>
              <span className="block text-xs text-muted-foreground">
                {clock(it.duration)}{!it.has_audio && " · không tiếng"} · {uses(it.id) ? `dùng ${uses(it.id)} lần` : "chưa dùng"}
              </span>
            </span>
            <IconButton label="Chèn vào cuối timeline" disabled={disabled} onClick={() => tl.current?.insertSource(it.id)}><Plus /></IconButton>
            <IconButton label="Chồng lên video từ đường chỉ" disabled={disabled} onClick={() => tl.current?.addLayer(it.id)}><Layers /></IconButton>
            {it.id !== 0 && it.has_audio && !p.segments.some((s) => (s.src_id ?? 0) === it.id) && p.status.stage !== "new" && (
              <IconButton label="Nhận dạng và dịch lời của video này" disabled={disabled || isActive(p)}
                onClick={() => api.retrySource(p.id, it.id).then(onApply).catch((err) => toast.error((err as Error).message))}><RotateCw /></IconButton>
            )}
            {it.id !== 0 && (
              <IconButton label={confirm === it.id ? "Bấm lần nữa để gỡ hẳn video này" : "Gỡ video khỏi dự án"} disabled={disabled || isActive(p)}
                className={cn(confirm === it.id && "bg-destructive/15 text-destructive")}
                onClick={() => {
                  if (confirm !== it.id) { setConfirm(it.id); setTimeout(() => setConfirm((c) => (c === it.id ? null : c)), 3500); return; }
                  setConfirm(null);
                  api.deleteSource(p.id, it.id).then(onApply).catch((err) => toast.error((err as Error).message));
                }}><Trash2 /></IconButton>
            )}
          </li>
        ))}
      </ul>
      {items.length === 1 && <Button variant="ghost" size="sm" className="justify-self-start" onClick={() => input.current?.click()}><Plus /> Thêm video thứ hai</Button>}
    </div>
  );
}
