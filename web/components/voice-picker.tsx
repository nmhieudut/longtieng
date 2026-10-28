"use client";

import { Check, Loader2, Pause, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type VoiceInfo, voiceSampleUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

// one shared player so starting a sample stops the previous one
let player: HTMLAudioElement | null = null;
const listeners = new Set<(id: string | null, loading: boolean) => void>();
const emit = (id: string | null, loading: boolean) => listeners.forEach((f) => f(id, loading));

function playSample(id: string) {
  if (player && player.dataset.voice === id && !player.paused) {
    player.pause();
    emit(null, false);
    return;
  }
  player?.pause();
  const a = new Audio(voiceSampleUrl(id));
  a.dataset.voice = id;
  player = a;
  emit(id, true);
  a.addEventListener("playing", () => player === a && emit(id, false));
  a.addEventListener("ended", () => player === a && emit(null, false));
  a.addEventListener("error", () => {
    if (player !== a) return;
    emit(null, false);
    toast.error("Không tạo được giọng mẫu. Thử lại sau.");
  });
  a.play().catch(() => {});
}

function usePlaying() {
  const [state, setState] = useState<{ id: string | null; loading: boolean }>({ id: null, loading: false });
  useEffect(() => {
    const f = (id: string | null, loading: boolean) => setState({ id, loading });
    listeners.add(f);
    return () => { listeners.delete(f); };
  }, []);
  return state;
}

export function VoicePicker({
  voices, value, onChange, disabled, className,
}: {
  voices: Record<string, VoiceInfo>;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  const playing = usePlaying();
  const groups = useMemo(() => {
    const g = new Map<string, [string, VoiceInfo][]>();
    for (const [id, v] of Object.entries(voices)) g.set(v.group, [...(g.get(v.group) ?? []), [id, v]]);
    return [...g.entries()];
  }, [voices]);

  if (!groups.length) return <div className="h-24 animate-pulse rounded-lg bg-muted" />;

  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)] gap-4 overflow-y-auto rounded-xl border p-2", className)} role="radiogroup" aria-label="Giọng đọc">
      {groups.map(([group, items]) => (
        <div key={group} className="grid grid-cols-[minmax(0,1fr)] gap-1">
          <p className="px-2 pt-1 text-xs font-medium text-muted-foreground">{group}</p>
          {items.map(([id, v]) => {
            const selected = id === value;
            const isPlaying = playing.id === id;
            return (
              <div
                key={id}
                role="radio"
                aria-checked={selected}
                tabIndex={disabled ? -1 : 0}
                onClick={() => !disabled && onChange(id)}
                onKeyDown={(e) => { if (!disabled && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onChange(id); } }}
                className={cn(
                  "flex min-w-0 cursor-pointer items-center gap-3 rounded-lg border border-transparent px-2 py-1.5 outline-none transition-colors",
                  "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/50",
                  selected && "border-primary/40 bg-primary/10 hover:bg-primary/10",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <Button
                  type="button"
                  size="icon"
                  variant={isPlaying ? "default" : "outline"}
                  className="size-8 shrink-0 rounded-full"
                  aria-label={`Nghe thử giọng ${v.label}`}
                  onClick={(e) => { e.stopPropagation(); playSample(id); }}
                >
                  {isPlaying && playing.loading ? <Loader2 className="animate-spin" /> : isPlaying ? <Pause /> : <Play />}
                </Button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={cn("text-sm", selected && "font-semibold text-primary")}>{v.label}</span>
                    <Badge variant="outline" className="h-4 px-1.5 text-[10px] text-muted-foreground">{v.gender}</Badge>
                  </div>
                  {v.note && <p className="truncate text-xs text-muted-foreground">{v.note}</p>}
                </div>
                {selected && <Check className="size-4 shrink-0 text-primary" />}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
