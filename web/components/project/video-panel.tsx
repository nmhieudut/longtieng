"use client";

import { type RefObject, useCallback, useEffect, useState } from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fmt, type Project, type Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

export type VideoView = "source" | "preview" | "final";

type Props = {
  project: Project;
  videoRef: RefObject<HTMLVideoElement | null>;
  src: string | null;
  view: VideoView;
  onView: (v: VideoView) => void;
  time: number;
  activeIdx: number;
  mask: Settings["mask"];
  onSeek: (t: number) => void;
  onTime: (t: number) => void;
  onLoaded: () => void;
};

export function VideoPanel({ project: p, videoRef, src, view, onView, time, activeIdx, mask, onSeek, onTime, onLoaded }: Props) {
  const box = useMaskBox(videoRef, src);
  const o = p.outputs;
  const dur = p.media?.duration ?? 0;

  return (
    <div className="grid gap-3">
      <div className="relative overflow-hidden rounded-xl bg-black">
        {src ? (
          <video
            ref={videoRef}
            src={src}
            controls
            playsInline
            preload="metadata"
            className="mx-auto block max-h-[58vh] w-full bg-black"
            onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
            onLoadedMetadata={onLoaded}
          />
        ) : (
          <div className="grid aspect-video place-items-center text-sm text-white/60">Đang tải video…</div>
        )}
        {mask.enabled && view === "source" && box && (
          <div
            className="pointer-events-none absolute border-2 border-dashed border-emerald-400 bg-emerald-400/15"
            style={{
              left: box.x,
              width: box.w,
              top: box.y + box.h * (1 - (mask.bottom + mask.height) / 100),
              height: (box.h * mask.height) / 100,
            }}
          >
            <span className="absolute -top-5 left-1 rounded bg-emerald-500 px-1.5 text-[10px] font-medium text-white">vùng che</span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={view}
          onValueChange={(v) => v && onView(v as VideoView)}
        >
          <ToggleGroupItem value="source">Video gốc</ToggleGroupItem>
          <ToggleGroupItem value="preview" disabled={!o.preview}>Xem thử</ToggleGroupItem>
          <ToggleGroupItem value="final" disabled={!o.final}>Bản lồng tiếng</ToggleGroupItem>
        </ToggleGroup>
        {dur > 0 && (
          <span className="font-mono text-xs text-muted-foreground tabular-nums">
            {view === "preview" ? "bản xem thử 30s" : `${fmt(time)} / ${fmt(dur)}`}
          </span>
        )}
      </div>

      {dur > 0 && p.segments.length > 0 && (
        <Timeline project={p} time={view === "preview" ? -1 : time} activeIdx={activeIdx} onSeek={onSeek} />
      )}
    </div>
  );
}

/** Where the picture actually sits inside the <video> box (letterboxing). */
function useMaskBox(videoRef: RefObject<HTMLVideoElement | null>, src: string | null) {
  const [box, setBox] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const measure = useCallback(() => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return setBox(null);
    const s = Math.min(v.clientWidth / v.videoWidth, v.clientHeight / v.videoHeight);
    const w = v.videoWidth * s, h = v.videoHeight * s;
    setBox({ x: (v.clientWidth - w) / 2, y: (v.clientHeight - h) / 2, w, h });
  }, [videoRef]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const ro = new ResizeObserver(measure);
    ro.observe(v);
    v.addEventListener("loadedmetadata", measure);
    measure();
    return () => { ro.disconnect(); v.removeEventListener("loadedmetadata", measure); };
  }, [videoRef, src, measure]);
  return box;
}

const FIT_COLOR = {
  ok: "bg-ok/70 hover:bg-ok",
  fast: "bg-fast/80 hover:bg-fast",
  overflow: "bg-over/80 hover:bg-over",
} as const;

function Timeline({ project: p, time, activeIdx, onSeek }: { project: Project; time: number; activeIdx: number; onSeek: (t: number) => void }) {
  const dur = p.media!.duration;
  const pct = (t: number) => `${(Math.min(Math.max(t, 0), dur) / dur) * 100}%`;
  return (
    <div className="grid gap-1">
      <div
        className="relative h-9 cursor-pointer overflow-hidden rounded-md bg-muted"
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - r.left) / r.width) * dur);
        }}
        role="slider"
        aria-label="Dòng thời gian các câu"
        aria-valuemin={0}
        aria-valuemax={dur}
        aria-valuenow={Math.max(0, time)}
      >
        {p.segments.map((s, i) => (
          <div
            key={s.id}
            title={`${fmt(s.start)} · ${s.vi || s.src}`}
            onClick={(e) => { e.stopPropagation(); onSeek(s.start + 0.01); }}
            className={cn(
              "absolute inset-y-1.5 rounded-sm transition-colors",
              !s.vi.trim() ? "bg-muted-foreground/30" : FIT_COLOR[s.fit?.status ?? "ok"],
              i === activeIdx && "ring-2 ring-foreground/70 ring-offset-1 ring-offset-muted",
            )}
            style={{ left: pct(s.start), width: `max(3px, ${((s.end - s.start) / dur) * 100}%)` }}
          />
        ))}
        {time >= 0 && <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-foreground" style={{ left: pct(time) }} />}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <Legend className="bg-ok/70" label="vừa khung" />
        <Legend className="bg-fast/80" label="đọc nhanh hơn để vừa" />
        <Legend className="bg-over/80" label="tràn, sẽ bị cắt" />
        <Legend className="bg-muted-foreground/30" label="chưa dịch" />
      </div>
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("size-2.5 rounded-sm", className)} />
      {label}
    </span>
  );
}
