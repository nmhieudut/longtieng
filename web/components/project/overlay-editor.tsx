"use client";

import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

/** Row of the timeline with the texts and stickers: drag a block to move it, drag its edges to change how long it shows. */
export function OverlayTrack({ items, pps, total, selectedId, disabled, onSelect, onChange, onScrub }: {
  items: Overlay[]; pps: number; total: number; selectedId: string | null; disabled: boolean;
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
      let a = o.start;
      let b = o.end;
      if (mode === "move") {
        const len = o.end - o.start;
        a = Math.min(Math.max(0, o.start + dt), Math.max(0, total - len));
        b = a + len;
      } else if (mode === "start") {
        a = Math.min(Math.max(0, o.start + dt), o.end - MIN_LEN);
      } else {
        b = Math.max(Math.min(total, o.end + dt), o.start + MIN_LEN);
      }
      onChange(base.map((x) => (x.id === o.id ? { ...x, start: +a.toFixed(2), end: +b.toFixed(2) } : x)));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="relative mt-1" style={{ height: OVERLAY_H }} onPointerDown={onScrub}>
      {items.map((o) => (
        <div key={o.id} role="button" tabIndex={0} title={o.kind === "text" ? o.text : "Hình dán"}
          onPointerDown={(e) => drag(e, o, "move")}
          className={cn("absolute top-0 flex h-full items-center overflow-hidden rounded-sm border px-1.5 text-[10px] leading-none",
            o.kind === "text" ? "border-primary/50 bg-primary/20" : "border-fast/60 bg-fast/25",
            selectedId === o.id && "ring-2 ring-primary", disabled ? "cursor-default" : "cursor-grab active:cursor-grabbing")}
          style={{ left: o.start * pps, width: Math.max((o.end - o.start) * pps - 1, 6) }}>
          <span className="pointer-events-none truncate">{o.kind === "text" ? o.text : "▣ Hình dán"}</span>
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
    <div className="grid gap-3 rounded-xl border p-3 sm:grid-cols-2" aria-label="Thuộc tính chữ hoặc hình dán">
      <p className="flex items-center justify-between text-xs font-medium sm:col-span-2">
        {o.kind === "text" ? "Chữ" : "Hình dán"} · {clock(o.start)}–{clock(o.end)}
        <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onDelete}><Trash2 /> Xoá</Button>
      </p>
      {o.kind === "text" && (
        <>
          <div className="grid gap-1 sm:col-span-2">
            <Label className="text-xs text-muted-foreground">Nội dung</Label>
            <Input value={o.text ?? ""} maxLength={200} disabled={disabled} onChange={(e) => onChange({ text: e.target.value })} />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Cỡ chữ</Label>
            <Slider min={0.03} max={0.2} step={0.005} disabled={disabled} value={[o.size]} onValueChange={([v]) => onChange({ size: v })} aria-label="Cỡ chữ" />
          </div>
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Màu chữ</Label>
            <div className="flex flex-wrap items-center gap-1.5">
              {SWATCHES.map((c) => (
                <button key={c} type="button" aria-label={`Màu ${c}`} disabled={disabled} onClick={() => onChange({ color: c })}
                  className={cn("size-6 rounded-full border", (o.color ?? "#ffffff") === c && "ring-2 ring-primary ring-offset-1")} style={{ background: c }} />
              ))}
              <input type="color" aria-label="Chọn màu khác" disabled={disabled} value={o.color ?? "#ffffff"}
                onChange={(e) => onChange({ color: e.target.value })} className="size-6 cursor-pointer rounded border bg-transparent p-0" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-xs"><Switch checked={!!o.box} disabled={disabled} onCheckedChange={(v) => onChange({ box: v })} /> Nền tối sau chữ</label>
          <label className="flex items-center gap-2 text-xs"><Switch checked={o.bold ?? true} disabled={disabled} onCheckedChange={(v) => onChange({ bold: v })} /> Chữ đậm</label>
        </>
      )}
      {o.kind === "image" && (
        <>
          <div className="grid gap-2 sm:col-span-2">
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
      <p className="text-[11px] text-muted-foreground sm:col-span-2">
        Thời gian tính theo video sau khi cắt ghép, nên không bị lệch khi bạn sửa đoạn. Xem thử ở video bên trái chỉ gần đúng; bản xuất mới chính xác.
      </p>
    </div>
  );
}
