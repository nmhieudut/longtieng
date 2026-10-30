"use client";

import { ArrowDownCircle, Loader2, RefreshCw, RotateCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type UpdateState } from "@/lib/api";

const mb = (n?: number) => (n ? `${Math.max(1, Math.round(n / 1048576))}MB` : "");

/** Header pill that appears when a newer release exists; installs it and restarts the app. */
export function UpdateButton() {
  const [u, setU] = useState<UpdateState | null>(null);
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);

  const refresh = useCallback(() => api.updateState().then(setU).catch(() => {}), []);
  useEffect(() => {
    refresh();
    // pick up a check made elsewhere (Settings dialog), and look again whenever the window comes back
    const onFocus = () => refresh();
    window.addEventListener("update-changed", refresh);
    window.addEventListener("focus", onFocus);
    const t = setInterval(refresh, 10 * 60 * 1000);
    return () => {
      clearInterval(t);
      window.removeEventListener("update-changed", refresh);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  async function checkNow() {
    setChecking(true);
    try {
      const next = await api.updateState(true);
      setU(next);
      if (next.stage === "available") setOpen(true);
      else if (next.stage === "error") toast.error(next.error ?? "Không kiểm tra được.");
      else toast.success(`Bạn đang dùng bản mới nhất (${next.current}).`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  const working = u && ["downloading", "installing", "restarting"].includes(u.stage);
  useEffect(() => {
    if (!working) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [working, refresh]);

  if (!u?.enabled) return null;
  if (!u.latest || !["available", "downloading", "installing", "restarting", "error"].includes(u.stage)) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label="Kiểm tra bản mới" disabled={checking} onClick={checkNow}>
            <RefreshCw className={checking ? "size-4 animate-spin" : "size-4"} />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Kiểm tra bản mới · đang dùng {u.current}</TooltipContent>
      </Tooltip>
    );
  }

  const size = u.kind === "patch" ? mb(u.latest.patch?.size) : mb(u.latest.mac?.size ?? u.latest.windows?.size);

  async function install() {
    try {
      setU(await api.updateApply());
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <>
      <Button size="sm" variant={working ? "outline" : "brand"} className="h-8 rounded-full" onClick={() => setOpen(true)}>
        {working ? <Loader2 className="animate-spin" /> : <ArrowDownCircle />}
        {working ? "Đang cập nhật…" : `Có bản mới ${u.latest.version}`}
      </Button>
      <Dialog open={open} onOpenChange={(o) => !working && setOpen(o)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cập nhật lên bản {u.latest.version}</DialogTitle>
            <DialogDescription>
              Bạn đang dùng bản {u.current}.{" "}
              {u.kind === "patch"
                ? `Cập nhật nhẹ${size ? ` (${size})` : ""}, xong trong vài giây.`
                : `Cập nhật đầy đủ${size ? ` (${size})` : ""}, mất vài phút tuỳ mạng.`}
            </DialogDescription>
          </DialogHeader>
          {u.latest.notes && (
            <div className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-sm">{u.latest.notes}</div>
          )}
          {u.stage === "downloading" && (
            <div className="grid gap-1.5">
              <Progress value={(u.progress ?? 0) * 100} />
              <p className="text-xs text-muted-foreground">Đang tải… {Math.round((u.progress ?? 0) * 100)}%</p>
            </div>
          )}
          {(u.stage === "installing" || u.stage === "restarting") && (
            <p className="flex items-center gap-2 text-sm"><Loader2 className="size-4 animate-spin" />
              {u.stage === "installing" ? "Đang cài…" : "Đang khởi động lại app…"}</p>
          )}
          {u.last_failed && u.stage !== "error" && <p className="text-sm text-destructive">{u.last_failed}</p>}
          {u.stage === "error" && <p className="text-sm text-destructive">{u.error}</p>}
          {(u.stage === "available" || u.stage === "error") && (
            <Button onClick={install}>
              {u.stage === "error" ? <RotateCw /> : <ArrowDownCircle />}
              {u.stage === "error" ? "Thử lại" : "Cập nhật & khởi động lại"}
            </Button>
          )}
          <p className="text-xs text-muted-foreground">Video và cài đặt của bạn được giữ nguyên.</p>
        </DialogContent>
      </Dialog>
    </>
  );
}
