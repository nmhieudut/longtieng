"use client";

import { Copy, Gauge, ImagePlus, Loader2, Plus, Redo2, RotateCw, Scissors, Trash2, Type, Undo2, Video, Volume2, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { addSource, api, fileUrl, isActive, type MusicTrack, type Overlay, type Project, type Settings } from "@/lib/api";
import { type Clip, clock, duplicateAt, full, layout, len, mapLines, MAX_SPEED, MIN_CLIP, MIN_SPEED, moveClip, removeAt, setProps, spd, splitAt, srcOf, totalLen, trans, trimEdge, uid } from "@/lib/timeline";
import { cn } from "@/lib/utils";

import { MUSIC_H, MusicBar, MusicInspector } from "./music-track";
import { OVERLAY_H, OverlayInspector, OverlayTrack } from "./overlay-editor";
import type { EditLog } from "./edit-log";
import type { OverlaysApi } from "./use-overlays";
import type { TimelineApi } from "./use-timeline";

const TRACK_H = 56;
const LINES_H = 22;
const RULER_H = 24;
const HANDLE_W = 8;
const SNAP_PX = 8;

type Props = {
  project: Project;
  tl: TimelineApi;
  overlays: OverlaysApi;
  editLog: EditLog;
  music: Settings["music"];
  onMusic: (patch: Partial<Settings["music"]>) => void;
  idx: number;                    // clip that is playing
  T: number;                      // playhead, output seconds
  playing: boolean;
  showPlayhead: boolean;          // false while an exported video is shown
  disabled: boolean;
  onSeekOut: (t: number) => void;
  onSelectClip: (i: number) => void;
  onTogglePlay: () => void;
  onApply: (p: Project) => void;
};

const STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

function ToolBtn({ label, hint, onClick, off, disabled, children }: {
  label: string; hint: string; onClick: () => void; off?: boolean; disabled: boolean; children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button type="button" variant="outline" size="sm" disabled={disabled || off} onClick={onClick} aria-label={label}>{children}</Button>
      </TooltipTrigger>
      <TooltipContent>{label} · {hint}</TooltipContent>
    </Tooltip>
  );
}

export function TimelinePanel({ project: p, tl, overlays, editLog, music, onMusic, idx, T, playing, showPlayhead, disabled, onSeekOut, onSelectClip, onTogglePlay, onApply }: Props) {
  const duration = p.media?.duration ?? 0;
  const { clips, commit, tweak, undo, redo } = tl;
  const rows = useMemo(() => layout(clips), [clips]);
  const total = totalLen(clips);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [zoom, setZoom] = useState(1);                 // 1 = whole edited video fits the panel
  const [selected, setSelected] = useState(0);
  const askedFilm = useRef(new Set<number>());
  const [addPct, setAddPct] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState<number | null>(null);
  const addInput = useRef<HTMLInputElement>(null);
  const extras = p.extra_sources ?? [];
  /** What the timeline needs to know about one video: how long it is, its thumbnails, its name. */
  const srcInfo = (src: number) => src === 0
    ? { duration, film: p.film, name: "Video 1" }
    : (() => { const e = extras.find((x) => x.id === src); return { duration: e?.duration ?? 0, film: e?.film, name: e?.name ?? `Video ${src + 1}` }; })();
  const [selOv, setSelOv] = useState<string | null>(null);
  const [selMusic, setSelMusic] = useState(false);
  const [tracks, setTracks] = useState<MusicTrack[]>([]);
  useEffect(() => { api.musicList().then(setTracks).catch(() => {}); }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // thumbnails: made once, the first time this tab is opened
  useEffect(() => {
    if (!p.media) return;
    const used = new Set([0, ...clips.map((c) => srcOf(c))]);
    for (const src of used) {
      const have = src === 0 ? p.film : p.extra_sources?.find((e) => e.id === src)?.film;
      if (have || askedFilm.current.has(src) || (src !== 0 && !p.extra_sources?.some((e) => e.id === src))) continue;
      askedFilm.current.add(src);
      api.filmstrip(p.id, src).then(onApply).catch(() => { askedFilm.current.delete(src); });
    }
  }, [p.film, p.extra_sources, p.id, p.media, clips, onApply]);

  const sel = Math.min(selected, clips.length - 1);
  const fit = Math.max(2, (width - 8) / Math.max(total, 1));
  const pps = fit * zoom;                               // pixels per second
  const contentW = Math.max(width - 8, total * pps);
  const lines = useMemo(() => mapLines(clips, p.segments), [clips, p.segments]);

  // undo / redo go through the edit log: back and forth in the order things were done, across clips and texts
  const doUndo = () => {
    const k = editLog.undo.pop();
    if (!k) return;
    if (k === "ov") overlays.undo(); else undo();
    editLog.redo.push(k);
  };
  const doRedo = () => {
    const k = editLog.redo.pop();
    if (!k) return;
    if (k === "ov") overlays.redo(); else redo();
    editLog.undo.push(k);
  };
  const tw = (next: Clip[], key: string) => tweak(next, key);

  // ---- operations
  const cut = () => {
    const r = splitAt(clips, T);
    if (!r) { toast.info("Đưa đường chỉ vị trí vào giữa một đoạn (cách mép ít nhất 0,2 giây) rồi bấm Cắt đôi."); return; }
    commit(r.clips);
    setSelected(r.idx);
  };

  const del = () => {
    if (selOv) { removeOverlay(); return; }
    if (clips.length <= 1) { toast.info("Phải còn ít nhất một đoạn. Muốn bỏ hết thì xoá video khỏi danh sách."); return; }
    commit(removeAt(clips, sel));
    setSelected(Math.max(0, sel - 1));
  };

  const dup = () => {
    commit(duplicateAt(clips, sel));
    setSelected(sel + 1);
  };

  // ---- texts and stickers
  const ovItems = overlays.items;
  const selectedOv = ovItems.find((o) => o.id === selOv) ?? null;
  const addOverlay = (kind: "text" | "image", image?: string) => {
    const start = Math.min(showPlayhead ? T : 0, Math.max(0, total - MIN_CLIP));
    const o: Overlay = {
      id: Math.random().toString(36).slice(2, 8), kind, start: +start.toFixed(2), end: +Math.min(total, start + 3).toFixed(2),
      x: 0.5, y: kind === "text" ? 0.2 : 0.35, size: kind === "text" ? 0.07 : 0.25,
      ...(kind === "text" ? { text: "Nhập chữ ở đây", color: "#ffffff", box: false, bold: true } : { image }),
    }; overlays.change([...ovItems, o], { now: true });
    setSelOv(o.id);
  };
  const addSticker = async () => {
    try {
      const list = await api.logoList();
      if (!list.length) { toast.info("Chưa có ảnh nào trong thư viện. Thêm hình dán rồi bấm “Tải ảnh mới” để chọn ảnh."); addOverlay("image", ""); return; }
      addOverlay("image", list[0].id);
    } catch (e) { toast.error((e as Error).message); }
  };
  const patchOverlay = (patch: Partial<Overlay>) => {
    overlays.change(ovItems.map((o) => (o.id === selOv ? { ...o, ...patch } : o)), { key: `p${selOv}${Object.keys(patch).join()}` });
  };
  const removeOverlay = () => { overlays.change(ovItems.filter((o) => o.id !== selOv), { now: true }); setSelOv(null); };

  const reset = () => { commit(full(duration)); setSelected(0); };

  // ---- keyboard (not while typing in a box). The listener is set up once and calls the latest handlers.
  const act = useRef({ cut, del, dup, undo: doUndo, redo: doRedo, onTogglePlay });
  useEffect(() => { act.current = { cut, del, dup, undo: doUndo, redo: doRedo, onTogglePlay }; });
  useEffect(() => {
    if (disabled) return;
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (t?.closest('[role="combobox"], [role="slider"], [role="listbox"], select')) return;
      if (e.key === " " && t?.closest("button")) return;   // Space presses a focused button
      const a = act.current;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); (e.shiftKey ? a.redo : a.undo)(); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); a.redo(); }
      else if (mod) return;
      else if (e.key === "s" || e.key === "S") { e.preventDefault(); a.cut(); }
      else if (e.key === "d" || e.key === "D") { e.preventDefault(); a.dup(); }
      else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); a.del(); }
      else if (e.key === " ") { e.preventDefault(); a.onTogglePlay(); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [disabled]);

  // ---- playhead: click or drag on the ruler / tracks
  const scrub = (e: React.PointerEvent<HTMLElement>) => {
    const host = e.currentTarget.closest("[data-tl-scroll]") as HTMLElement;
    const at = (ev: { clientX: number }) => {
      const x = ev.clientX - host.getBoundingClientRect().left + host.scrollLeft - 4;
      onSeekOut(Math.min(Math.max(x / pps, 0), total));
    };
    at(e);
    const move = (ev: PointerEvent) => at(ev);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // ---- trim: drag a clip edge. The edge snaps to the playhead.
  const startTrim = (e: React.PointerEvent, i: number, side: "start" | "end") => {
    if (disabled) return;
    e.stopPropagation();
    e.preventDefault();
    const before = clips;
    const x0 = e.clientX;
    const base = side === "start" ? clips[i].start : clips[i].end;
    const move = (ev: PointerEvent) => {
      let src = base + ((ev.clientX - x0) / pps) * spd(clips[i]);
      const head = clips[i].start + (T - rows[i].at) * spd(clips[i]);           // source second under the playhead, if it is in this clip
      if (T >= rows[i].at && T <= rows[i].at + len(clips[i]) && Math.abs(src - head) * (pps / spd(clips[i])) < SNAP_PX) src = head;
      tl.preview(trimEdge(before, i, side, src, srcInfo(srcOf(before[i])).duration));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      tl.settle(before);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // ---- reorder: drag a clip sideways past its neighbour
  const startMove = (e: React.PointerEvent, i: number) => {
    if (disabled || clips.length < 2) return;
    const before = clips;
    const x0 = e.clientX;
    let at = i;
    let moved = false;
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 6) return;
      moved = true;
      const r = layout(before);
      const center = r[i].at * pps + (len(before[i]) * pps) / 2 + dx;
      let target = 0;
      r.forEach((row, k) => { if (k !== i && center > row.at * pps + (len(row.clip) * pps) / 2) target = k + (k < i ? 1 : 0); });
      if (target !== at) { at = target; tl.preview(moveClip(before, i, target)); setSelected(target); }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (moved && at !== i) { tl.settle(before); }
      else tl.preview(before);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // ruler ticks
  const step = STEPS.find((s) => s * pps >= 70) ?? STEPS[STEPS.length - 1];
  const ticks = Array.from({ length: Math.floor(total / step) + 1 }, (_, k) => k * step);

  if (!p.media) return <p className="p-4 text-sm text-muted-foreground">Video chưa sẵn sàng.</p>;

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ToolBtn disabled={disabled} label="Cắt đôi tại đường chỉ" hint="S" onClick={cut}><Scissors /> Cắt đôi</ToolBtn>
        <ToolBtn disabled={disabled} label="Xoá đoạn đang chọn" hint="Delete" onClick={del} off={clips.length <= 1}><Trash2 /> Xoá</ToolBtn>
        <ToolBtn disabled={disabled} label="Nhân đôi đoạn đang chọn" hint="D" onClick={dup}><Copy /> Nhân đôi</ToolBtn>
        <span className="mx-1 h-5 w-px bg-border" />
        <ToolBtn disabled={disabled || isActive(p) || addPct !== null} label="Thêm video khác vào cuối timeline" hint="nhận dạng và dịch lời luôn"
          onClick={() => addInput.current?.click()}>{addPct !== null ? <Loader2 className="animate-spin" /> : <Video />} Thêm video</ToolBtn>
        <input ref={addInput} type="file" hidden accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv,.m4v"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            setAddPct(0);
            try { onApply(await addSource(p.id, f, setAddPct)); toast.success("Đã thêm video, đang nhận dạng và dịch lời."); }
            catch (err) { toast.error((err as Error).message); }
            finally { setAddPct(null); }
          }} />
        <ToolBtn disabled={disabled} label="Thêm chữ tại đường chỉ" hint="chữ hiện 3 giây" onClick={() => addOverlay("text")}><Type /> Chữ</ToolBtn>
        <ToolBtn disabled={disabled} label="Thêm hình dán tại đường chỉ" hint="ảnh trong thư viện" onClick={addSticker}><ImagePlus /> Hình dán</ToolBtn>
        <span className="mx-1 h-5 w-px bg-border" />
        <ToolBtn disabled={disabled} label="Hoàn tác" hint="Ctrl/⌘ Z" onClick={doUndo} off={!tl.canUndo && !overlays.canUndo}><Undo2 /></ToolBtn>
        <ToolBtn disabled={disabled} label="Làm lại" hint="Ctrl/⌘ Shift Z" onClick={doRedo} off={!tl.canRedo && !overlays.canRedo}><Redo2 /></ToolBtn>
        <Button type="button" variant="ghost" size="sm" disabled={disabled || !tl.edited} onClick={reset}>Về nguyên bản</Button>
        <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          <ZoomIn className="size-4" />
          <Slider className="w-28" min={1} max={12} step={0.1} value={[zoom]} onValueChange={([v]) => setZoom(v)} aria-label="Phóng to timeline" />
        </span>
      </div>

      <p className="font-mono text-xs tabular-nums text-muted-foreground">
        {clock(showPlayhead ? T : 0)} / {clock(total)}
        {tl.edited && <span className="ml-2 font-sans text-primary">· đã chỉnh, video xuất sẽ dài {clock(total)} (gốc {clock(duration)})</span>}
        {disabled && <span className="ml-2 font-sans text-fast-foreground">· đang xuất video, tạm khoá chỉnh sửa</span>}
      </p>

      {addPct !== null && <p className="text-xs text-muted-foreground">Đang tải video lên… {Math.round(addPct * 100)}%</p>}
      {extras.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">Video đã thêm:</span>
          {extras.map((e) => (
            <span key={e.id} className="flex items-center gap-1 rounded-full border px-2 py-1">
              <Video className="size-3" /> <span className="max-w-32 truncate" title={e.name}>{e.name}</span> · {clock(e.duration)}
              {e.has_audio && !p.segments.some((s) => (s.src_id ?? 0) === e.id) && (
                <button type="button" disabled={disabled || isActive(p)} className="rounded p-0.5 text-fast-foreground hover:bg-accent"
                  title="Video này chưa có lời thoại: nhận dạng và dịch lại"
                  onClick={() => api.retrySource(p.id, e.id).then(onApply).catch((err) => toast.error((err as Error).message))}><RotateCw className="size-3" /></button>
              )}
              <button type="button" disabled={disabled} className="rounded p-0.5 hover:bg-accent" title="Chèn vào cuối timeline"
                onClick={() => { commit([...clips, { id: uid(), src: e.id, start: 0, end: e.duration }]); setSelected(clips.length); }}><Plus className="size-3" /></button>
              <button type="button" disabled={disabled || isActive(p)} className={cn("rounded p-0.5 hover:bg-accent", confirmDel === e.id && "bg-destructive/15 text-destructive")}
                title={confirmDel === e.id ? "Bấm lần nữa để gỡ hẳn video này" : "Gỡ video khỏi dự án"}
                onClick={() => {
                  if (confirmDel !== e.id) { setConfirmDel(e.id); setTimeout(() => setConfirmDel((c) => (c === e.id ? null : c)), 3500); return; }
                  setConfirmDel(null);
                  api.deleteSource(p.id, e.id).then(onApply).catch((err) => toast.error((err as Error).message));
                }}><Trash2 className="size-3" /></button>
            </span>
          ))}
        </div>
      )}

      <div ref={box} className="rounded-xl border bg-muted/30">
        <div data-tl-scroll className="relative overflow-x-auto overflow-y-hidden px-1 pb-2" style={{ height: RULER_H + TRACK_H + LINES_H + OVERLAY_H + MUSIC_H + 30 }}>
          <div className="relative" style={{ width: contentW, height: "100%" }}>
            {/* ruler */}
            <div className="relative cursor-pointer select-none" style={{ height: RULER_H }} onPointerDown={scrub}>
              {ticks.map((t) => (
                <span key={t} className="absolute top-0 h-full border-l border-border pl-1 text-[10px] leading-6 text-muted-foreground" style={{ left: t * pps }}>
                  {clock(t)}
                </span>
              ))}
            </div>

            {/* video track */}
            <div className="relative mt-1" style={{ height: TRACK_H }} onPointerDown={scrub}>
              {rows.map(({ clip, at }, i) => {
                const w = len(clip) * pps;
                const info = srcInfo(srcOf(clip));
                return (
                  <div key={clip.id} role="button" tabIndex={0} aria-label={`Đoạn ${i + 1}, ${clock(len(clip))}`}
                    className={cn(
                      "group absolute top-0 overflow-hidden rounded-md border-2 bg-secondary text-left shadow-sm",
                      sel === i ? "border-primary" : "border-border",
                      i === idx && showPlayhead && "ring-1 ring-primary/40",
                      disabled ? "cursor-default" : "cursor-grab active:cursor-grabbing",
                    )}
                    style={{
                      left: at * pps, width: Math.max(w - 2, 4), height: TRACK_H,
                      backgroundImage: info.film ? `url(${fileUrl(p.id, info.film.file)})` : undefined,
                      backgroundSize: info.film ? `${(info.duration * pps) / spd(clip)}px 100%` : undefined,
                      backgroundPosition: info.film ? `${(-clip.start * pps) / spd(clip)}px 0` : undefined,
                    }}
                    onPointerDown={(e) => {
                      e.stopPropagation();
                      setSelected(i);
                      setSelOv(null);
                      setSelMusic(false);
                      onSelectClip(i);
                      startMove(e, i);
                    }}
                    onKeyDown={(e) => { if (e.key === "Enter") setSelected(i); }}
                  >
                    {!info.film && <Loader2 className="m-2 size-4 animate-spin text-muted-foreground" />}
                    <span className="pointer-events-none absolute bottom-0.5 left-1 max-w-[90%] truncate rounded bg-black/55 px-1 text-[10px] font-medium text-white">
                      {srcOf(clip) !== 0 && <>{info.name} · </>}{clock(len(clip))}
                    </span>
                    {(spd(clip) !== 1 || (clip.volume ?? 1) !== 1) && (
                      <span className="pointer-events-none absolute right-1 top-0.5 flex gap-1 rounded bg-black/55 px-1 text-[10px] font-medium text-white">
                        {spd(clip) !== 1 && <span>{+spd(clip).toFixed(2)}×</span>}
                        {(clip.volume ?? 1) === 0 ? <span>tắt tiếng</span> : (clip.volume ?? 1) !== 1 && <span>{Math.round((clip.volume ?? 1) * 100)}%</span>}
                      </span>
                    )}
                    {i > 0 && trans(clips, i) > 0 && (
                      <span className="pointer-events-none absolute inset-y-0 left-0 bg-gradient-to-r from-primary/60 to-transparent" style={{ width: trans(clips, i) * pps }} />
                    )}
                    {!!clip.fade_in && <span className="pointer-events-none absolute inset-y-0 left-0 bg-gradient-to-r from-black/70 to-transparent" style={{ width: clip.fade_in * pps }} />}
                    {!!clip.fade_out && <span className="pointer-events-none absolute inset-y-0 right-0 bg-gradient-to-l from-black/70 to-transparent" style={{ width: clip.fade_out * pps }} />}
                    {/* edge handles */}
                    {(["start", "end"] as const).map((side) => (
                      <span key={side} onPointerDown={(e) => startTrim(e, i, side)}
                        className={cn("absolute top-0 h-full cursor-col-resize bg-primary/0 hover:bg-primary/50", side === "start" ? "left-0" : "right-0")}
                        style={{ width: HANDLE_W }} />
                    ))}
                  </div>
                );
              })}
            </div>

            {/* the dubbed lines */}
            <div className="relative mt-1" style={{ height: LINES_H }} onPointerDown={scrub}>
              {lines.map((s, k) => (
                <div key={`${s.id}-${k}`} title={s.vi || "(chưa có lời)"}
                  className={cn("absolute top-0 h-full overflow-hidden rounded-sm border px-1 text-[10px] leading-5",
                    !s.vi.trim() ? "border-border bg-muted text-muted-foreground"
                      : s.fit?.status === "overflow" ? "border-over/50 bg-over/25"
                        : s.fit?.status === "fast" ? "border-fast/60 bg-fast/25" : "border-ok/50 bg-ok/20")}
                  style={{ left: s.out0 * pps, width: Math.max((s.out1 - s.out0) * pps - 1, 2) }}>
                  <span className="pointer-events-none whitespace-nowrap">{s.vi}</span>
                </div>
              ))}
            </div>

            {/* texts and stickers */}
            <OverlayTrack items={ovItems} pps={pps} total={total} selectedId={selOv} disabled={disabled}
              onSelect={(id) => { setSelOv(id); setSelMusic(false); }} onChange={(next) => { overlays.change(next, { key: `drag${selOv}` }); }} onScrub={scrub} />

            {/* background music */}
            <MusicBar music={music} tracks={tracks} total={total} pps={pps} selected={selMusic}
              onSelect={() => { setSelMusic(true); setSelOv(null); }} />

            {/* playhead */}
            {showPlayhead && (
              <div className="pointer-events-none absolute top-0 z-10" style={{ left: T * pps, height: RULER_H + TRACK_H + LINES_H + OVERLAY_H + MUSIC_H + 16 }}>
                <div className="h-full w-0.5 -translate-x-1/2 bg-primary" />
                <div className="absolute -top-0.5 left-0 size-3 -translate-x-1/2 rounded-full bg-primary" />
              </div>
            )}
          </div>
        </div>
      </div>

      {selMusic && !selectedOv && <MusicInspector music={music} tracks={tracks} disabled={disabled} onChange={onMusic} />}

      {selectedOv && <OverlayInspector o={selectedOv} total={total} disabled={disabled} onChange={patchOverlay} onDelete={removeOverlay} />}

      {!selectedOv && !selMusic && clips[sel] && (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-xl border p-3 sm:grid-cols-2" aria-label="Thuộc tính đoạn đang chọn">
          <p className="text-xs font-medium sm:col-span-2">
            Đoạn {sel + 1}/{clips.length} · {clock(len(clips[sel]))}
          </p>
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground"><Gauge className="size-3.5" /> Tốc độ
              <span className="ml-auto font-mono text-foreground">{+spd(clips[sel]).toFixed(2)}×</span>
            </Label>
            <Slider min={MIN_SPEED} max={MAX_SPEED} step={0.05} disabled={disabled} value={[spd(clips[sel])]}
              onValueChange={([v]) => tw(setProps(clips, sel, { speed: v }), `speed${sel}`)} aria-label="Tốc độ" />
            <div className="flex flex-wrap gap-1">
              {[0.5, 1, 1.5, 2, 4].map((v) => (
                <button key={v} type="button" disabled={disabled}
                  onClick={() => tw(setProps(clips, sel, { speed: v }), `speedchip${sel}${v}`)}
                  className={cn("rounded-full border px-2 py-0.5 text-[11px] hover:bg-accent", spd(clips[sel]) === v && "border-primary bg-primary/10 text-primary")}>
                  {v}×
                </button>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground"><Volume2 className="size-3.5" /> Âm thanh gốc của đoạn
              <span className="ml-auto font-mono text-foreground">{Math.round((clips[sel].volume ?? 1) * 100)}%</span>
            </Label>
            <Slider min={0} max={2} step={0.05} disabled={disabled} value={[clips[sel].volume ?? 1]}
              onValueChange={([v]) => tw(setProps(clips, sel, { volume: v }), `vol${sel}`)} aria-label="Âm thanh gốc" />
            <p className="text-[11px] text-muted-foreground">0% là tắt tiếng đoạn này (giọng lồng vẫn đọc). Trên 100% chỉ có khi xuất, nghe thử bị giới hạn ở 100%.</p>
          </div>
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">Mờ dần vào
              <span className="ml-auto font-mono text-foreground">{(clips[sel].fade_in ?? 0).toFixed(1)}s</span>
            </Label>
            <Slider min={0} max={2} step={0.1} disabled={disabled} value={[clips[sel].fade_in ?? 0]}
              onValueChange={([v]) => tw(setProps(clips, sel, { fade_in: v }), `fi${sel}`)} aria-label="Mờ dần vào" />
          </div>
          <div className="grid gap-2 sm:col-span-2">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">Chuyển cảnh từ đoạn trước (pha trộn hai đoạn)
              <span className="ml-auto font-mono text-foreground">{sel === 0 ? "—" : `${(clips[sel].transition ?? 0).toFixed(1)}s`}</span>
            </Label>
            <Slider min={0} max={2} step={0.1} disabled={disabled || sel === 0} value={[clips[sel].transition ?? 0]}
              onValueChange={([v]) => tw(setProps(clips, sel, { transition: v }), `tr${sel}`)} aria-label="Chuyển cảnh" />
            <p className="text-[11px] text-muted-foreground">
              {sel === 0 ? "Đoạn đầu tiên không có đoạn trước." : "Hai đoạn chồng lên nhau đúng bằng thời gian này (tối đa một nửa đoạn ngắn hơn), nên video xuất ngắn đi tương ứng. Nghe thử chưa hiện hiệu ứng, bản xuất mới có."}
            </p>
          </div>
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">Mờ dần ra
              <span className="ml-auto font-mono text-foreground">{(clips[sel].fade_out ?? 0).toFixed(1)}s</span>
            </Label>
            <Slider min={0} max={2} step={0.1} disabled={disabled} value={[clips[sel].fade_out ?? 0]}
              onValueChange={([v]) => tw(setProps(clips, sel, { fade_out: v }), `fo${sel}`)} aria-label="Mờ dần ra" />
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Bấm vào thanh hoặc kéo đường chỉ để chọn vị trí. Kéo hai mép một đoạn để cắt bớt, kéo cả đoạn sang cạnh để đổi thứ tự.
        Các câu lồng tiếng nằm trong phần bị cắt sẽ tự bỏ, câu còn lại tự dời theo. Video gốc không bị đổi; bấm Xuất để ra bản đã cắt ghép.
        {" "}{playing ? "" : `Đoạn ngắn nhất ${MIN_CLIP} giây.`}
      </p>
    </div>
  );
}
