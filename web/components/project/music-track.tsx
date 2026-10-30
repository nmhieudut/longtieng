"use client";

import { Music2 } from "lucide-react";
import { useState } from "react";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { fmt, type MusicTrack, type Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

type Music = Settings["music"];
export const MUSIC_H = 24;

/** Row of the timeline for the background music: it runs under the whole video and loops. */
export function MusicBar({ music, tracks, total, pps, selected, onSelect }: {
  music: Music; tracks: MusicTrack[]; total: number; pps: number; selected: boolean; onSelect: () => void;
}) {
  const name = tracks.find((t) => t.id === music.track)?.name;
  return (
    <div className="relative mt-1" style={{ height: MUSIC_H }}>
      <div role="button" tabIndex={0} onPointerDown={(e) => { e.stopPropagation(); onSelect(); }}
        onKeyDown={(e) => { if (e.key === "Enter") onSelect(); }}
        className={cn("absolute left-0 top-0 flex h-full cursor-pointer items-center gap-1 overflow-hidden rounded-sm border px-1.5 text-[10px]",
          name ? "border-ok/50 bg-ok/20" : "border-dashed border-border bg-muted/40 text-muted-foreground",
          selected && "ring-2 ring-primary")}
        style={{ width: name ? Math.max(total * pps - 1, 40) : Math.min(Math.max(total * pps, 40), 200) }}>
        <Music2 className="size-3 shrink-0" />
        <span className="pointer-events-none truncate">{name ? `${name} · ${Math.round(music.volume * 100)}%` : "Thêm nhạc nền"}</span>
      </div>
    </div>
  );
}

/** Choose the track and set how loud it is, where in the track it starts and whether it makes way for the voice. */
export function MusicInspector({ music, tracks, disabled, onChange }: {
  music: Music; tracks: MusicTrack[]; disabled: boolean; onChange: (patch: Partial<Music>) => void;
}) {
  // sliders move the numbers at once; the change is sent when the thumb is released
  const [local, setLocal] = useState<Partial<Music>>({});
  const vol = local.volume ?? music.volume;
  const start = local.start ?? music.start;
  const cur = tracks.find((t) => t.id === music.track);
  const send = (patch: Partial<Music>) => { setLocal({}); onChange(patch); };

  return (
    <div className="grid gap-3 rounded-xl border p-3 sm:grid-cols-2" aria-label="Nhạc nền">
      <p className="text-xs font-medium sm:col-span-2">Nhạc nền · chạy dưới cả video, hết bài thì lặp lại</p>
      <div className="grid gap-2 sm:col-span-2">
        <Label className="text-xs text-muted-foreground">Bài nhạc</Label>
        <Select value={music.track ?? "none"} disabled={disabled} onValueChange={(v) => send({ track: v === "none" ? null : v, start: 0 })}>
          <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Không dùng nhạc</SelectItem>
            {tracks.map((t) => <SelectItem key={t.id} value={t.id}>{t.name} · {fmt(t.duration)}</SelectItem>)}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">Thêm hoặc xoá bài trong thư viện ở Cài đặt → Nhạc nền.</p>
      </div>
      {cur && (
        <>
          <div className="grid gap-2">
            <Label className="flex items-center text-xs text-muted-foreground">Âm lượng <span className="ml-auto font-mono text-foreground">{Math.round(vol * 100)}%</span></Label>
            <Slider min={0} max={1} step={0.01} disabled={disabled} value={[vol]} aria-label="Âm lượng nhạc"
              onValueChange={([v]) => setLocal((l) => ({ ...l, volume: v }))} onValueCommit={([v]) => send({ volume: v })} />
          </div>
          <div className="grid gap-2">
            <Label className="flex items-center text-xs text-muted-foreground">Bắt đầu từ giây thứ <span className="ml-auto font-mono text-foreground">{fmt(start)}</span></Label>
            <Slider min={0} max={Math.max(1, cur.duration - 1)} step={0.5} disabled={disabled} value={[start]} aria-label="Bắt đầu bài nhạc từ"
              onValueChange={([v]) => setLocal((l) => ({ ...l, start: v }))} onValueCommit={([v]) => send({ start: v })} />
          </div>
          <label className="flex items-center gap-2 text-xs sm:col-span-2">
            <Switch checked={music.duck} disabled={disabled} onCheckedChange={(v) => send({ duck: v })} /> Nhạc nhỏ lại khi có giọng đọc
          </label>
        </>
      )}
    </div>
  );
}
