"use client";

import { Loader2, Scissors } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/lib/api";
import { clock } from "@/lib/timeline";

type Result = { keep: [number, number][]; removed: number; total: number };

/** Cut the silent stretches out of the selected clip: it is replaced by the parts that are kept (ordinary clips). */
export function SilenceDialog({ open, onOpenChange, projectId, src, start, end, onApply }: {
  open: boolean; onOpenChange: (o: boolean) => void; projectId: string; src: number; start: number; end: number;
  onApply: (keep: [number, number][]) => void;
}) {
  const [profile, setProfile] = useState("default");
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBusy(true);
    api.trimSilence(projectId, { src, start, end, profile })
      .then((r) => { if (alive) setRes(r); })
      .catch((e) => { if (alive) { toast.error((e as Error).message); onOpenChange(false); } })
      .finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [open, profile, projectId, src, start, end, onOpenChange]);

  const parts = res?.keep.length ?? 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cắt khoảng lặng</DialogTitle>
          <DialogDescription>Bỏ những chỗ im lặng của đoạn đang chọn. Kết quả là các đoạn nhỏ trên timeline, vẫn kéo mép hoặc hoàn tác được.</DialogDescription>
        </DialogHeader>
        <ToggleGroup type="single" variant="outline" className="w-full" value={profile} onValueChange={(v) => v && setProfile(v)}>
          <ToggleGroupItem value="natural" className="flex-1">Tự nhiên</ToggleGroupItem>
          <ToggleGroupItem value="default" className="flex-1">Vừa</ToggleGroupItem>
          <ToggleGroupItem value="tight" className="flex-1">Chặt (jump cut)</ToggleGroupItem>
        </ToggleGroup>
        <p className="min-h-10 text-sm text-muted-foreground" aria-live="polite">
          {busy || !res ? <span className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Đang nghe tìm chỗ im lặng…</span>
            : res.removed < 0.3 ? "Không thấy chỗ im lặng nào đáng cắt ở mức này. Thử mức “Chặt”."
              : <>Bỏ <b className="text-foreground">{clock(res.removed)}</b> im lặng, tạo <b className="text-foreground">{parts}</b> đoạn. Đoạn ngắn đi từ {clock(res.total)} còn {clock(res.total - res.removed)}.</>}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Thôi</Button>
          <Button disabled={busy || !res || res.removed < 0.3} onClick={() => { if (res) { onApply(res.keep); onOpenChange(false); } }}>
            <Scissors /> Cắt
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
