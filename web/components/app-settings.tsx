"use client";

import { CheckCircle2, ExternalLink, KeyRound, Loader2, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type AppSettings } from "@/lib/api";

/** App-wide settings (gear icon): OpenAI key, where data lives, speech engine. */
export function AppSettingsButton({ onChanged }: { onChanged?: () => void }) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<AppSettings | null>(null);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);

  async function checkUpdate() {
    setChecking(true);
    try {
      const u = await api.updateState(true);
      if (!u.enabled) toast.info("Bản chạy từ mã nguồn không tự cập nhật. Dùng git pull.");
      else if (u.stage === "available") toast.success(`Có bản mới ${u.latest?.version}. Bấm nút “Có bản mới” trên thanh trên cùng.`);
      else if (u.stage === "error") toast.error(u.error ?? "Không kiểm tra được.");
      else toast.success("Bạn đang dùng bản mới nhất.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    if (open) api.appSettings().then(setInfo).catch((e) => toast.error(e.message));
  }, [open]);

  async function save(value: string) {
    setSaving(true);
    try {
      const next = await api.saveAppSettings({ openai_key: value });
      setInfo(next);
      setKey("");
      toast.success(value ? "Đã lưu key. Từ giờ dịch và caption dùng OpenAI." : "Đã xoá key. Dịch bằng Google.");
      onChanged?.();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Cài đặt">
          <Settings2 className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cài đặt</DialogTitle>
          <DialogDescription>Áp dụng cho mọi video trên máy này.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2">
          <Label htmlFor="openai-key" className="flex items-center gap-1.5"><KeyRound className="size-4" /> OpenAI API key</Label>
          {info?.openai_key_set ? (
            <p className="flex items-center gap-1.5 text-sm text-ok">
              <CheckCircle2 className="size-4" /> Đang dùng key <span className="font-mono">{info.openai_key_hint}</span>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              Chưa có key: dịch bằng Google (kém tự nhiên hơn), không có caption AI và giọng OpenAI.
            </p>
          )}
          <form
            className="flex gap-2"
            onSubmit={(e) => { e.preventDefault(); if (key.trim()) save(key.trim()); }}
          >
            <Input id="openai-key" type="password" autoComplete="off" spellCheck={false} placeholder="sk-…"
              value={key} onChange={(e) => setKey(e.target.value)} className="font-mono" />
            <Button type="submit" disabled={saving || !key.trim()}>
              {saving ? <Loader2 className="animate-spin" /> : null} Lưu
            </Button>
          </form>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground">
              Lấy key ở platform.openai.com <ExternalLink className="size-3" />
            </a>
            <span>Mỗi video ~6 phút tốn khoảng 500–1.000đ.</span>
            {info?.openai_key_set && (
              <button type="button" className="text-destructive underline underline-offset-2" disabled={saving} onClick={() => save("")}>
                Xoá key
              </button>
            )}
          </div>
          <p className="text-xs text-muted-foreground">Key chỉ lưu trên máy này, không gửi đi đâu ngoài OpenAI.</p>
        </div>

        {info && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t pt-4 text-xs">
            <dt className="text-muted-foreground">Nhận dạng giọng</dt>
            <dd>{info.stt_engine}{info.stt_model_ready ? "" : " · tải model ~1.6GB ở lần chạy đầu"}</dd>
            <dt className="text-muted-foreground">Dữ liệu lưu ở</dt>
            <dd className="break-all font-mono">{info.data_dir}</dd>
            <dt className="text-muted-foreground">Phiên bản</dt>
            <dd className="flex flex-wrap items-center gap-2">
              {info.version}
              <button type="button" className="underline underline-offset-2 hover:text-foreground" disabled={checking}
                onClick={checkUpdate}>
                {checking ? "Đang kiểm tra…" : "Kiểm tra bản mới"}
              </button>
            </dd>
          </dl>
        )}
      </DialogContent>
    </Dialog>
  );
}
