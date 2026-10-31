"use client";

import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { api, type Logo, logoUrl, type Overlay } from "@/lib/api";
import { clock } from "@/lib/timeline";
import { cn } from "@/lib/utils";

export const OVERLAY_H = 24;
const MIN_LEN = 0.2;
const HANDLE = 6;
const SWATCHES = ["#ffffff", "#ffd400", "#ff4d4d", "#4dd2ff", "#7cfc00", "#000000"];

/** Lane of each item: the first lane where it does not overlap an earlier one, so nothing hides behind another. */
export function overlayLanes(items: Overlay[]): number[] {
  const order = items.map((o, i) => i).sort((a, b) => items[a].start - items[b].start);
  const ends: number[] = [];
  const lane = new Array<number>(items.length).fill(0);
  for (const i of order) {
    let k = ends.findIndex((e) => e <= items[i].start + 1e-6);
    if (k < 0) { k = ends.length; ends.push(0); }
    ends[k] = items[i].end;
    lane[i] = k;
  }
  return lane;
}

/** Row of the timeline with the texts and stickers: drag a block to move it, drag its edges to change how long it shows. */
export function OverlayTrack({ items, pps, total, selectedId, disabled, srcDuration, snaps, onSelect, onChange, onScrub }: {
  items: Overlay[]; pps: number; total: number; selectedId: string | null; disabled: boolean;
  snaps: number[];                         // times (seconds) the edges stick to: playhead, clip edges, other items
  srcDuration: (src: number) => number;   // length of a video, so a video layer cannot run past its end
  onSelect: (id: string) => void; onChange: (next: Overlay[]) => void; onScrub: (e: React.PointerEvent<HTMLElement>) => void;
}) {
  const drag = (e: React.PointerEvent, o: Overlay, mode: "move" | "start" | "end") => {
    e.stopPropagation();
    onSelect(o.id);
    if (disabled) return;
    e.preventDefault();
    const x0 = e.clientX;
    const base = items;
    const move = (ev: PointerEvent) => {
      const dt = (ev.clientX - x0) / pps;
      const thr = 8 / pps;
      const near = (t: number) => { let best: number | null = null; for (const s of snaps) if (Math.abs(s - t) < thr && (best === null || Math.abs(s - t) < Math.abs(best - t))) best = s; return best; };
      let a = o.start;
      let b = o.end;
      if (mode === "move") {
        const len = o.end - o.start;
        a = Math.min(Math.max(0, o.start + dt), Math.max(0, total - len));
        const sa = near(a), sb = near(a + len);   // the front or the back edge sticks
        if (sa !== null) a = sa; else if (sb !== null) a = sb - len;
        b = a + len;
      } else if (mode === "start") {
        a = Math.min(Math.max(o.kind === "video" ? o.start - (o.from ?? 0) : 0, o.start + dt), o.end - MIN_LEN);
        a = near(a) ?? a;
      } else {
        const room = o.kind === "video" ? o.start + srcDuration(o.src ?? 0) - (o.from ?? 0) : total;   // the layer's own video ends there
        b = Math.max(Math.min(room, o.end + dt), o.start + MIN_LEN);
        b = near(b) ?? b;
      }
      // trimming the front of a video layer moves where in the video it starts, so the picture stays in step
      onChange(base.map((x) => (x.id === o.id ? { ...x, start: +a.toFixed(2), end: +b.toFixed(2), ...(x.kind === "video" ? { from: +Math.max(0, (o.from ?? 0) + (a - o.start)).toFixed(2) } : {}) } : x)));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const lane = overlayLanes(items);
  const lanes = Math.max(1, ...lane.map((l) => l + 1));
  return (
    <div data-track="overlay" className="relative mt-1" style={{ height: OVERLAY_H * lanes }} onPointerDown={onScrub}>
      {items.map((o, n) => (
        <div key={o.id} role="button" tabIndex={0} title={o.kind === "text" ? o.text : o.kind === "video" ? "Video chồng" : "Hình dán"}
          onPointerDown={(e) => drag(e, o, "move")}
          className={cn("absolute flex items-center overflow-hidden rounded-sm border px-1.5 text-[10px] leading-none",
            o.kind === "text" ? "border-primary/50 bg-primary/20" : o.kind === "video" ? "border-ok/60 bg-ok/20" : "border-fast/60 bg-fast/25",
            selectedId === o.id && "ring-2 ring-primary", disabled ? "cursor-default" : "cursor-grab active:cursor-grabbing")}
          style={{ left: o.start * pps, top: lane[n] * OVERLAY_H, width: Math.max((o.end - o.start) * pps - 1, 6), height: OVERLAY_H - 2 }}>
          <span className="pointer-events-none truncate">{o.kind === "text" ? o.text : o.kind === "video" ? "▶ Video chồng" : "▣ Hình dán"}</span>
          {(["start", "end"] as const).map((side) => (
            <span key={side} onPointerDown={(e) => drag(e, o, side)}
              className={cn("absolute top-0 h-full cursor-col-resize hover:bg-primary/50", side === "start" ? "left-0" : "right-0")}
              style={{ width: HANDLE }} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Settings of the selected text or sticker. */
export function OverlayInspector({ o, total, disabled, onChange, onDelete }: {
  o: Overlay; total: number; disabled: boolean; onChange: (patch: Partial<Overlay>) => void; onDelete: () => void;
}) {
  const [logos, setLogos] = useState<Logo[]>([]);
  const [uploading, setUploading] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (o.kind === "image") api.logoList().then(setLogos).catch(() => {});
  }, [o.kind]);

  async function upload(f: File | undefined) {
    if (!f) return;
    setUploading(true);
    try {
      const l = await api.logoUpload(f);
      setLogos((xs) => [l, ...xs]);
      onChange({ image: l.id });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  const num = (label: string, value: number, key: "start" | "end") => (
    <div className="grid gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Input type="number" min={0} max={total} step={0.1} disabled={disabled} value={value}
        onChange={(e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) onChange({ [key]: Math.max(0, +v.toFixed(2)) }); }} />
    </div>
  );

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3 rounded-xl border p-3" aria-label="Thuộc tính chữ hoặc hình dán">
      <p className="flex items-center justify-between text-xs font-medium">
        {o.kind === "text" ? "Chữ" : o.kind === "video" ? "Video chồng" : "Hình dán"} · {clock(o.start)}–{clock(o.end)}
        <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onDelete}><Trash2 /> Xoá</Button>
      </p>
      {o.kind === "text" && (
        <>
          <div className="grid gap-1">
            <Label className="text-xs text-muted-foreground">Nội dung</Label>
            <Textarea rows={2} value={o.text ?? ""} maxLength={200} disabled={disabled} onChange={(e) => onChange({ text: e.target.value })} />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Cỡ chữ</Label>
            <Slider min={0.03} max={0.3} step={0.005} disabled={disabled} value={[o.size]} onValueChange={([v]) => onChange({ size: v })} aria-label="Cỡ chữ" />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Màu chữ</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {SWATCHES.map((c) => (
                <button key={c} type="button" aria-label={`Màu ${c}`} disabled={disabled} onClick={() => onChange({ color: c })}
                  className={cn("size-7 rounded-full border", (o.color ?? "#ffffff") === c && "ring-2 ring-primary ring-offset-1")} style={{ background: c }} />
              ))}
              <input type="color" aria-label="Chọn màu khác" disabled={disabled} value={o.color ?? "#ffffff"}
                onChange={(e) => onChange({ color: e.target.value })} className="size-7 cursor-pointer rounded border bg-transparent p-0" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs"><Switch checked={!!o.box} disabled={disabled} onCheckedChange={(v) => onChange({ box: v })} /> Nền tối sau chữ</label>
          <label className="flex items-center gap-2 text-xs"><Switch checked={o.bold ?? true} disabled={disabled} onCheckedChange={(v) => onChange({ bold: v })} /> Chữ đậm</label>
        </>
      )}
      {o.kind === "video" && (
        <>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Độ rộng ({Math.round(o.size * 100)}%)</Label>
            <Slider min={0.1} max={1} step={0.01} disabled={disabled} value={[o.size]} onValueChange={([v]) => onChange({ size: v })} aria-label="Độ rộng" />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Độ đậm ({Math.round((o.opacity ?? 1) * 100)}%)</Label>
            <Slider min={0.1} max={1} step={0.05} disabled={disabled} value={[o.opacity ?? 1]} onValueChange={([v]) => onChange({ opacity: v })} aria-label="Độ đậm" />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Âm thanh của video này ({Math.round((o.volume ?? 1) * 100)}%)</Label>
            <Slider min={0} max={1} step={0.05} disabled={disabled} value={[o.volume ?? 1]} onValueChange={([v]) => onChange({ volume: v })} aria-label="Âm thanh video chồng" />
          </div>
        </>
      )}
      {o.kind === "image" && (
        <>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Hình</Label>
            <div className="flex flex-wrap items-center gap-2">
              {logos.map((l) => (
                <button key={l.id} type="button" disabled={disabled} onClick={() => onChange({ image: l.id })} title={l.name}
                  className={cn("size-12 overflow-hidden rounded-md border bg-muted p-0.5", o.image === l.id && "ring-2 ring-primary")}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={logoUrl(l.id)} alt={l.name} className="size-full object-contain" />
                </button>
              ))}
              <Button type="button" variant="outline" size="sm" disabled={disabled || uploading} onClick={() => file.current?.click()}>
                {uploading ? <Loader2 className="animate-spin" /> : <ImagePlus />} Tải ảnh mới
              </Button>
              <input ref={file} type="file" hidden accept="image/png,image/jpeg,image/webp"
                onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
            </div>
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Kích thước</Label>
            <Slider min={0.05} max={0.8} step={0.01} disabled={disabled} value={[o.size]} onValueChange={([v]) => onChange({ size: v })} aria-label="Kích thước" />
          </div>
        </>
      )}
      <div className="grid gap-2">
        <Label className="text-xs text-muted-foreground">Vị trí ngang ({Math.round(o.x * 100)}%)</Label>
        <Slider min={0} max={1} step={0.01} disabled={disabled} value={[o.x]} onValueChange={([v]) => onChange({ x: v })} aria-label="Vị trí ngang" />
      </div>
      <div className="grid gap-2">
        <Label className="flex items-center gap-1.5 text-xs text-muted-foreground">Vị trí dọc ({Math.round(o.y * 100)}%)
          <span className="ml-auto flex gap-1">
            {([["Trên", 0.15], ["Giữa", 0.5], ["Dưới", 0.85]] as const).map(([name, v]) => (
              <button key={name} type="button" disabled={disabled} onClick={() => onChange({ y: v })}
                className="rounded-full border px-2 py-0.5 text-[11px] hover:bg-accent">{name}</button>
            ))}
          </span>
        </Label>
        <Slider min={0} max={1} step={0.01} disabled={disabled} value={[o.y]} onValueChange={([v]) => onChange({ y: v })} aria-label="Vị trí dọc" />
      </div>
      {num("Hiện từ giây", o.start, "start")}
      {num("Đến giây", o.end, "end")}
      <p className="text-[11px] text-muted-foreground">
        Thời gian tính theo video sau khi cắt ghép, nên không bị lệch khi bạn sửa đoạn. Xem thử ở video bên trái chỉ gần đúng; bản xuất mới chính xác.
      </p>
    </div>
  );
}
