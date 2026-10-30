"use client";

import { BadgeCheck, Film, Maximize, Minimize, Pause, Play, SkipBack, Timer, Volume2, VolumeX } from "lucide-react";
import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { Slider } from "@/components/ui/slider";
import { fmt, type Overlay, type Project, type Settings } from "@/lib/api";
import { colorIsDefault, cssFilter, vignetteOverlay, warmthOverlay } from "@/lib/color";
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
  color: Settings["color"];
  srcId: number;           // which video file is loaded (0 = main)
  edited: boolean;         // the timeline has cuts, so an exported video is in another time than the lines
  overlays: Overlay[];     // texts and stickers (output time), shown roughly over the original video
  outTime: number;         // playhead in output time
  playing: boolean;
  volume: number;
  muted: boolean;
  onVolume: (v: number) => void;
  onMuted: (m: boolean) => void;
  onTogglePlay: () => void;
  scrub?: { value: number; max: number; seek: (t: number) => void };   // set when the bar runs in output time (edited original)
  onSeek: (t: number) => void;
  onTime: (t: number) => void;
  onLoaded: () => void;
};

const VIEWS = [
  { v: "source", label: "Video gốc", icon: Film },
  { v: "preview", label: "Bản xem thử 30 giây", icon: Timer },
  { v: "final", label: "Bản lồng tiếng đã xuất", icon: BadgeCheck },
] as const;

export function VideoPanel({
  project: p, videoRef, src, view, onView, time, activeIdx, mask, color, srcId, edited, overlays, outTime,
  playing, volume, muted, onVolume, onMuted, onTogglePlay, scrub, onSeek, onTime, onLoaded,
}: Props) {
  const box = useMaskBox(videoRef, src);
  const stage = useRef<HTMLDivElement>(null);
  const [vdur, setVdur] = useState(0);
  const [full, setFull] = useState(false);
  const o = p.outputs;
  const dur = srcId === 0 ? p.media?.duration ?? 0 : p.extra_sources?.find((e) => e.id === srcId)?.duration ?? 0;
  // the exported videos already have the colours baked in; only the original is adjusted live
  const live = view === "source" && !colorIsDefault(color);
  const warm = live ? warmthOverlay(color) : null;
  const vig = live ? vignetteOverlay(color) : null;

  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === stage.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);

  const max = scrub ? scrub.max : view === "source" ? dur : vdur || dur;
  const value = scrub ? scrub.value : time;
  const go = (t: number) => {
    if (scrub) { scrub.seek(t); return; }
    const v = videoRef.current;
    if (v) { v.currentTime = t; onTime(t); }
  };
  const fullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else stage.current?.requestFullscreen().catch(() => {});
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div ref={stage} className="group/stage relative min-h-0 flex-1 overflow-hidden rounded-xl bg-black">
        {src ? (
          <video
            ref={videoRef}
            src={src}
            playsInline
            preload="metadata"
            className="absolute inset-0 size-full cursor-pointer bg-black object-contain"
            style={live ? { filter: cssFilter(color) } : undefined}
            onClick={onTogglePlay}
            onTimeUpdate={(e) => onTime(e.currentTarget.currentTime)}
            onLoadedMetadata={(e) => { setVdur(e.currentTarget.duration || 0); onLoaded(); }}
            onDurationChange={(e) => setVdur(e.currentTarget.duration || 0)}
          />
        ) : (
          <div className="grid size-full place-items-center text-sm text-white/60">Đang tải video…</div>
        )}
        {src && !playing && (
          <button type="button" onClick={onTogglePlay} aria-label="Phát"
            className="absolute left-1/2 top-1/2 grid size-14 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-black/50 text-white backdrop-blur-sm transition hover:bg-black/70">
            <Play className="size-6 translate-x-0.5 fill-current" />
          </button>
        )}
        {warm && <div className="pointer-events-none absolute inset-0 mix-blend-soft-light" style={warm} />}
        {vig && <div className="pointer-events-none absolute inset-0" style={{ background: vig }} />}
        {live && (
          <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">
            Xem nhanh · gần đúng
          </span>
        )}
        {box && overlays.filter((o) => outTime >= o.start && outTime <= o.end).map((o) => {
          const base = Math.min(box.w, box.h);
          const style = { left: box.x + o.x * box.w, top: box.y + o.y * box.h, transform: "translate(-50%, -50%)" } as const;
          return o.kind === "text" ? (
            <div key={o.id} className="pointer-events-none absolute whitespace-pre-wrap text-center leading-tight"
              style={{ ...style, maxWidth: box.w * 0.9, color: o.color ?? "#fff", fontSize: o.size * base, fontWeight: o.bold === false ? 400 : 700,
                background: o.box ? "rgba(0,0,0,.55)" : undefined, padding: o.box ? "0.15em 0.4em" : undefined,
                textShadow: o.box ? undefined : "0 0 3px #000, 0 0 3px #000, 0 0 3px #000" }}>
              {o.text}
            </div>
          ) : o.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={o.id} src={`/api/logos/${o.image}/file`} alt="" className="pointer-events-none absolute" style={{ ...style, width: o.size * box.w }} />
          ) : null;
        })}
        {mask.enabled && view === "source" && box && (
          <div
            className="pointer-events-none absolute border-2 border-dashed border-orange-300 bg-orange-300/15"
            style={{
              left: box.x,
              width: box.w,
              top: box.y + box.h * (1 - (mask.bottom + mask.height) / 100),
              height: (box.h * mask.height) / 100,
            }}
          >
            <span className="absolute -top-5 left-1 rounded bg-orange-400 px-1.5 text-[10px] font-medium text-white">vùng che</span>
          </div>
        )}
        {full && (
          <div className="absolute inset-x-0 bottom-0 flex items-center gap-2 bg-gradient-to-t from-black/80 to-transparent p-3 text-white">
            <button type="button" aria-label={playing ? "Tạm dừng" : "Phát"} onClick={onTogglePlay} className="rounded p-1 hover:bg-white/15">
              {playing ? <Pause className="size-5" /> : <Play className="size-5" />}
            </button>
            <input type="range" aria-label="Vị trí" min={0} max={max || 1} step={0.05} value={Math.min(Math.max(value, 0), max || 1)}
              onChange={(e) => go(parseFloat(e.target.value))} className="h-1 flex-1 cursor-pointer accent-white" />
            <span className="font-mono text-xs tabular-nums">{fmt(value)} / {fmt(max)}</span>
            <button type="button" aria-label="Thoát toàn màn hình" onClick={fullscreen} className="rounded p-1 hover:bg-white/15"><Minimize className="size-5" /></button>
          </div>
        )}
      </div>

      {/* transport bar: the player's own controls live here, outside the picture */}
      <div className="flex shrink-0 items-center gap-1.5 rounded-xl border bg-card px-2 py-1">
        <IconButton label={playing ? "Tạm dừng" : "Phát"} hint="Space" onClick={onTogglePlay} disabled={!src}>
          {playing ? <Pause /> : <Play />}
        </IconButton>
        <IconButton label="Về đầu" onClick={() => go(0)} disabled={!src}><SkipBack /></IconButton>
        <span className="w-24 shrink-0 text-center font-mono text-xs tabular-nums text-muted-foreground">
          {view === "preview" && !vdur ? "xem thử 30s" : `${fmt(value)} / ${fmt(max)}`}
        </span>
        <Slider className="min-w-16 flex-1" aria-label="Vị trí video" min={0} max={max || 1} step={0.05} disabled={!src || !max}
          value={[Math.min(Math.max(value, 0), max || 1)]} onValueChange={([v]) => go(v)} />
        <IconButton label={muted || volume === 0 ? "Bật tiếng" : "Tắt tiếng"} onClick={() => { if (muted || volume === 0) { onMuted(false); if (volume === 0) onVolume(1); } else onMuted(true); }}>
          {muted || volume === 0 ? <VolumeX /> : <Volume2 />}
        </IconButton>
        <Slider className="hidden w-20 shrink-0 sm:flex" aria-label="Âm lượng" min={0} max={1} step={0.05}
          value={[muted ? 0 : volume]} onValueChange={([v]) => { onVolume(v); if (muted && v > 0) onMuted(false); }} />
        <span className="mx-1 h-5 w-px bg-border" />
        {VIEWS.map(({ v, label, icon: Icon }) => (
          <IconButton key={v} label={label} active={view === v} disabled={v !== "source" && !o[v]} onClick={() => onView(v)}><Icon /></IconButton>
        ))}
        <IconButton label="Toàn màn hình" onClick={fullscreen} disabled={!src}><Maximize /></IconButton>
      </div>

      {dur > 0 && p.segments.length > 0 && !(edited && view !== "source") && (
        <Timeline project={p} srcId={srcId} dur={dur} time={view === "preview" ? -1 : time} activeIdx={activeIdx} onSeek={onSeek} />
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

function Timeline({ project: p, srcId, dur, time, activeIdx, onSeek }: { project: Project; srcId: number; dur: number; time: number; activeIdx: number; onSeek: (t: number) => void }) {
  const pct = (t: number) => `${(Math.min(Math.max(t, 0), dur) / dur) * 100}%`;
  return (
    <div className="shrink-0">
      <div
        title="Mỗi khối là một câu, bấm để nhảy tới. Xanh: vừa khung · vàng: đọc nhanh hơn · đỏ: tràn, sẽ bị cắt · xám: chưa dịch"
        className="relative h-6 cursor-pointer overflow-hidden rounded-md bg-muted"
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
        {p.segments.map((s, i) => (s.src_id ?? 0) !== srcId ? null : (
          <div
            key={s.id}
            title={`${fmt(s.start)} · ${s.vi || s.src}`}
            onClick={(e) => { e.stopPropagation(); onSeek(s.start + 0.01); }}
            className={cn(
              "absolute inset-y-1 rounded-sm transition-colors",
              !s.vi.trim() ? "bg-muted-foreground/30" : FIT_COLOR[s.fit?.status ?? "ok"],
              i === activeIdx && "ring-2 ring-foreground/70 ring-offset-1 ring-offset-muted",
            )}
            style={{ left: pct(s.start), width: `max(3px, ${((s.end - s.start) / dur) * 100}%)` }}
          />
        ))}
        {time >= 0 && <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-foreground" style={{ left: pct(time) }} />}
      </div>
    </div>
  );
}
