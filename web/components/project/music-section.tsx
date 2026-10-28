"use client";

import { Check, Loader2, Music2, Pause, Play, Trash2, Upload, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, fmt, type MusicTrack, musicUrl, type Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Section, SliderField } from "./settings-ui";

type Music = Settings["music"];

export function MusicSection({ music, disabled, onChange }: {
  music: Music;
  disabled: boolean;
  onChange: (m: Partial<Music>) => void;
}) {
  const [tracks, setTracks] = useState<MusicTrack[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.musicList().then(setTracks).catch((e) => toast.error(e.message));
    return () => audio.current?.pause();
  }, []);

  const current = tracks?.find((t) => t.id === music.track) ?? null;

  function toggle(t: MusicTrack) {
    if (playing === t.id) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    const a = new Audio(musicUrl(t.id));
    a.currentTime = t.id === music.track ? music.start : 0;
    a.onended = () => setPlaying(null);
    a.play().catch(() => toast.error("Không phát được bài này."));
    audio.current = a;
    setPlaying(t.id);
  }

  async function upload(f: File) {
    setUploading(true);
    try {
      const t = await api.musicUpload(f);
      setTracks((xs) => [...(xs ?? []), t]);
      onChange({ track: t.id, start: 0 });
      toast.success(`Đã thêm “${t.name}”`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove(t: MusicTrack) {
    try {
      await api.musicDelete(t.id);
      setTracks((xs) => (xs ?? []).filter((x) => x.id !== t.id));
      if (music.track === t.id) onChange({ track: null });
      if (playing === t.id) { audio.current?.pause(); setPlaying(null); }
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <Section
      value="music"
      icon={<Music2 />}
      title="Nhạc nền"
      summary={current ? `${current.name} · ${Math.round(music.volume * 100)}%` : "Không"}
    >
      <Button size="sm" variant="outline" className="justify-self-start" disabled={uploading} onClick={() => input.current?.click()}>
        {uploading ? <Loader2 className="animate-spin" /> : <Upload />} Tải nhạc lên thư viện
      </Button>
      <input ref={input} type="file" hidden accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac,.aac"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />

      <div className="grid max-h-64 grid-cols-[minmax(0,1fr)] gap-1 overflow-y-auto rounded-lg border p-2" role="radiogroup" aria-label="Nhạc nền">
        <Row selected={!music.track} disabled={disabled} onSelect={() => onChange({ track: null })}
          icon={<span className="grid size-8 place-items-center rounded-full border text-muted-foreground"><VolumeX className="size-4" /></span>}
          name="Không dùng nhạc" />
        {tracks === null && <div className="h-10 animate-pulse rounded-md bg-muted" />}
        {tracks?.map((t) => (
          <Row key={t.id} selected={music.track === t.id} disabled={disabled}
            onSelect={() => onChange({ track: t.id, start: 0 })}
            icon={
              <Button type="button" size="icon" variant={playing === t.id ? "default" : "outline"}
                className="size-8 shrink-0 rounded-full" aria-label={`Nghe thử ${t.name}`}
                onClick={(e) => { e.stopPropagation(); toggle(t); }}>
                {playing === t.id ? <Pause /> : <Play />}
              </Button>
            }
            name={t.name}
            meta={fmt(t.duration)}
            extra={
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" size="icon" variant="ghost" aria-label={`Xoá ${t.name}`}
                    className="size-7 text-muted-foreground hover:text-destructive" onClick={(e) => e.stopPropagation()}>
                    <Trash2 />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Xoá “{t.name}” khỏi thư viện?</AlertDialogTitle>
                    <AlertDialogDescription>Video nào đang dùng bài này sẽ không còn nhạc nền khi xuất lại.</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Huỷ</AlertDialogCancel>
                    <AlertDialogAction variant="destructive" onClick={() => remove(t)}>Xoá</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            }
          />
        ))}
        {tracks?.length === 0 && (
          <p className="px-2 py-1 text-xs text-muted-foreground">Thư viện trống. Bấm “Tải nhạc lên” (mp3, m4a, wav… tối đa 50MB).</p>
        )}
      </div>

      {current && (
        <>
          <SliderField label="Âm lượng nhạc" value={music.volume} min={0} max={1} step={0.05} disabled={disabled}
            show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => onChange({ volume: v })} />
          <SliderField label="Bắt đầu nhạc từ" value={Math.min(music.start, current.duration)} min={0}
            max={Math.max(1, Math.floor(current.duration - 1))} step={1} disabled={disabled}
            show={(v) => fmt(v)} onChange={(v) => onChange({ start: v })} />
          <div className="flex items-center justify-between gap-3">
            <div>
              <Label className="text-sm">Tự giảm nhạc khi có giọng đọc</Label>
              <p className="text-xs text-muted-foreground">Nhạc nhỏ lại lúc lồng tiếng, to lên ở chỗ ngắt.</p>
            </div>
            <Switch checked={music.duck} disabled={disabled} onCheckedChange={(v) => onChange({ duck: v })} />
          </div>
          <p className="text-xs text-muted-foreground">
            Nhạc ngắn hơn video sẽ tự lặp, cuối video nhỏ dần. Dùng nhạc miễn phí bản quyền để Facebook không tắt tiếng.
          </p>
        </>
      )}
    </Section>
  );
}

function Row({ selected, disabled, onSelect, icon, name, meta, extra }: {
  selected: boolean; disabled: boolean; onSelect: () => void;
  icon: React.ReactNode; name: string; meta?: string; extra?: React.ReactNode;
}) {
  return (
    <div
      role="radio"
      aria-checked={selected}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onSelect()}
      onKeyDown={(e) => { if (!disabled && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSelect(); } }}
      className={cn(
        "flex cursor-pointer items-center gap-3 rounded-md border border-transparent px-2 py-1.5 outline-none transition-colors",
        "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50",
        selected && "border-primary/40 bg-primary/10 hover:bg-primary/10",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      {icon}
      <span className={cn("min-w-0 flex-1 truncate text-sm", selected && "font-semibold text-primary")}>{name}</span>
      {meta && <span className="font-mono text-xs text-muted-foreground">{meta}</span>}
      {extra}
      {selected && <Check className="size-4 shrink-0 text-primary" />}
    </div>
  );
}
