"use client";

import { Loader2, RefreshCw, Volume2 } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type Fit, fmt, isActive, type Project, type Segment, slotOf, ttsFresh } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  project: Project;
  activeIdx: number;
  playing: boolean;
  onSeek: (t: number) => void;
  onSave: (sid: number, vi: string) => Promise<void>;
  onRegen: (sid: number) => Promise<void>;
  onPlay: (sid: number) => void;
};

export function SegmentList({ project: p, activeIdx, playing, onSeek, onSave, onRegen, onPlay }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const busy = isActive(p);

  // follow playback
  useEffect(() => {
    if (!playing || activeIdx < 0) return;
    const row = box.current?.querySelector<HTMLElement>(`[data-idx="${activeIdx}"]`);
    row?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIdx, playing]);

  if (!p.segments.length) {
    return (
      <div className="flex flex-col items-center gap-3 px-6 py-16 text-center text-sm text-muted-foreground">
        {busy && <Loader2 className="size-6 animate-spin" />}
        {busy ? "Bản dịch sẽ hiện ở đây khi nhận dạng và dịch xong." : "Chưa có câu nào."}
      </div>
    );
  }

  return (
    <div ref={box} className="divide-y">
      {p.segments.map((s, i) => (
        <Row
          key={s.id}
          seg={s}
          idx={i}
          slot={slotOf(p, i)}
          fresh={ttsFresh(s, p.settings)}
          active={i === activeIdx}
          busy={busy}
          onSeek={onSeek}
          onSave={onSave}
          onRegen={onRegen}
          onPlay={onPlay}
        />
      ))}
    </div>
  );
}

type RowProps = {
  seg: Segment;
  idx: number;
  slot: number;
  fresh: boolean;
  active: boolean;
  busy: boolean;
} & Pick<Props, "onSeek" | "onSave" | "onRegen" | "onPlay">;

const Row = memo(function Row({ seg, idx, slot, fresh, active, busy, onSeek, onSave, onRegen, onPlay }: RowProps) {
  const [draft, setDraftState] = useState(seg.vi);
  const draftRef = useRef(seg.vi); // timers read this, not a stale closure
  const setDraft = (v: string) => { draftRef.current = v; setDraftState(v); };
  const [focused, setFocused] = useState(false);
  const [regen, setRegen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const status = !seg.vi.trim() ? null : seg.fit?.status;

  // take server value unless the user is typing
  useEffect(() => {
    if (!focused && !timer.current) { draftRef.current = seg.vi; setDraftState(seg.vi); }
  }, [seg.vi, focused]);

  const flush = async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    const vi = draftRef.current.replace(/\s+/g, " ").trim();
    if (vi !== seg.vi) await onSave(seg.id, vi);
  };

  return (
    <div
      data-idx={idx}
      className={cn(
        "grid grid-cols-[3.25rem_1fr] gap-x-3 gap-y-2 border-l-[3px] border-l-transparent px-4 py-3 transition-colors",
        active && "bg-primary/5",
        status === "fast" && "border-l-fast",
        status === "overflow" && "border-l-over",
      )}
    >
      <button
        type="button"
        onClick={() => onSeek(seg.start + 0.01)}
        className="h-fit rounded font-mono text-xs text-primary tabular-nums hover:underline"
        title="Nhảy tới câu này"
      >
        {fmt(seg.start)}
      </button>
      <p className="text-sm leading-relaxed text-muted-foreground">{seg.src}</p>

      <span />
      <Textarea
        value={draft}
        disabled={busy}
        rows={1}
        placeholder="Nhập bản dịch…"
        className={cn("min-h-9 resize-none field-sizing-content text-[15px]", status === "overflow" && "border-over focus-visible:ring-over/30")}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); flush(); }}
        onChange={(e) => {
          setDraft(e.target.value);
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => { timer.current = null; flush(); }, 800);
        }}
      />

      <span />
      <div className="flex flex-wrap items-center gap-2">
        <FitBadge fit={status ? seg.fit : null} />
        {fresh && seg.tts && (
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            {seg.tts.secs.toFixed(1)}s / {slot.toFixed(1)}s
          </span>
        )}
        <div className="ml-auto flex gap-1">
          {fresh && (
            <Button size="xs" variant="ghost" onClick={() => onPlay(seg.id)}>
              <Volume2 /> Nghe
            </Button>
          )}
          <Button
            size="xs"
            variant="outline"
            disabled={busy || regen || !draft.trim()}
            onClick={async () => {
              setRegen(true);
              try { await flush(); await onRegen(seg.id); } finally { setRegen(false); }
            }}
          >
            {regen ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {seg.tts ? "Tạo lại giọng" : "Tạo giọng"}
          </Button>
        </div>
      </div>
    </div>
  );
});

function FitBadge({ fit }: { fit: Fit }) {
  if (!fit) return null;
  const est = fit.estimated ? "~" : "";
  const tip = fit.estimated ? "Ước tính trước khi tạo giọng" : `Đã tăng tốc ×${fit.speed}`;
  const body =
    fit.status === "ok" ? <Badge variant="outline" className="text-ok">{fit.estimated ? "ước tính vừa" : "vừa"}</Badge>
      : fit.status === "fast" ? <Badge className="bg-fast/20 text-fast-foreground">{est}nhanh ×{fit.need}</Badge>
        : <Badge className="bg-over/15 text-over">{est}tràn ×{fit.need} · nên rút gọn</Badge>;
  return (
    <Tooltip>
      <TooltipTrigger asChild><span>{body}</span></TooltipTrigger>
      <TooltipContent>{tip}</TooltipContent>
    </Tooltip>
  );
}
