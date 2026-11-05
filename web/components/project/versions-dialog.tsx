"use client";

import { History, Loader2, RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, type Project, type Version } from "@/lib/api";

const when = (t: number) => new Date(t * 1000).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });

/** Saved states of the edit (timeline, texts, look). One is saved after every export; restoring saves the current one first. */
export function VersionsDialog({ open, onOpenChange, projectId, onRestore }: {
  open: boolean; onOpenChange: (o: boolean) => void; projectId: string; onRestore: (p: Project) => void;
}) {
  const [list, setList] = useState<Version[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    api.versions(projectId).then(setList).catch((e) => toast.error((e as Error).message));
  }, [open, projectId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><History className="size-4" /> Lịch sử phiên bản</DialogTitle>
          <DialogDescription>Mỗi lần xuất xong app tự lưu một bản (timeline, chữ, hình dán, màu, logo). Khôi phục không mất bản hiện tại.</DialogDescription>
        </DialogHeader>
        <Button variant="outline" disabled={busy !== null}
          onClick={async () => { setBusy("save"); try { setList(await api.makeVersion(projectId, "Lưu tay")); toast.success("Đã lưu phiên bản."); } catch (e) { toast.error((e as Error).message); } finally { setBusy(null); } }}>
          {busy === "save" ? <Loader2 className="animate-spin" /> : <Save />} Lưu phiên bản hiện tại
        </Button>
        <ul className="grid max-h-72 gap-1.5 overflow-y-auto">
          {list === null && <li className="text-sm text-muted-foreground">Đang tải…</li>}
          {list?.length === 0 && <li className="text-sm text-muted-foreground">Chưa có phiên bản nào.</li>}
          {list?.map((v) => (
            <li key={v.id} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{v.label}</span>
                <span className="block text-xs text-muted-foreground">{when(v.at)} · {v.clips} đoạn{v.overlays ? ` · ${v.overlays} chữ/hình dán` : ""}</span>
              </span>
              <Button size="sm" variant="outline" disabled={busy !== null}
                onClick={async () => {
                  setBusy(v.id);
                  try { onRestore(await api.restoreVersion(projectId, v.id)); setList(await api.versions(projectId)); toast.success("Đã khôi phục."); onOpenChange(false); }
                  catch (e) { toast.error((e as Error).message); } finally { setBusy(null); }
                }}>
                {busy === v.id ? <Loader2 className="animate-spin" /> : <RotateCcw />} Khôi phục
              </Button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
