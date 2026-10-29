"use client";

import { CheckCircle2, Download, ExternalLink, FolderOpen, KeyRound, Loader2, Mic, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type AppSettings, desktopApi } from "@/lib/api";

/** App-wide settings (gear icon): OpenAI key, where data lives, speech engine. */
export function AppSettingsButton({ onChanged }: { onChanged?: () => void }) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<AppSettings | null>(null);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [folder, setFolder] = useState("");
  const [savingFolder, setSavingFolder] = useState(false);

  async function checkUpdate() {
    setChecking(true);
    try {
      const u = await api.updateState(true);
      window.dispatchEvent(new Event("update-changed"));  // the header button shows it right away
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
    if (open) api.appSettings().then((i) => { setInfo(i); setFolder(i.output_dir); }).catch((e) => toast.error(e.message));
  }, [open]);

  // while the voice model downloads, ask for its progress every second
  const dl = info?.vieneu;
  useEffect(() => {
    if (!open || !dl?.running) return;
    const t = setInterval(() => { api.appSettings().then(setInfo).catch(() => {}); }, 1000);
    return () => clearInterval(t);
  }, [open, dl?.running]);

  async function downloadVoices() {
    try {
      await api.vieneuDownload();
      setInfo(await api.appSettings());
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function saveFolder(value: string) {
    setSavingFolder(true);
    try {
      const next = await api.saveAppSettings({ output_dir: value });
      setInfo(next);
      setFolder(next.output_dir);
      window.dispatchEvent(new Event("app-settings-changed"));
      toast.success(next.output_dir ? "Đã lưu. Mỗi video xuất xong sẽ được chép vào thư mục này." : "Đã tắt chép tự động.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSavingFolder(false);
    }
  }

  async function pickFolder() {
    const picked = await desktopApi()?.pick_folder(folder);
    if (picked) { setFolder(picked); saveFolder(picked); }
  }

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
          <Settings className="size-4" />
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

        <div className="grid gap-2 border-t pt-4">
          <Label htmlFor="out-dir" className="flex items-center gap-1.5"><FolderOpen className="size-4" /> Thư mục lưu video xuất</Label>
          <p className="text-xs text-muted-foreground">
            Video xuất xong sẽ được chép thêm vào thư mục này. Chọn một thư mục trong Google Drive, OneDrive hoặc Dropbox
            (cài app của họ trên máy) thì file tự đồng bộ lên đó để dùng ở máy khác.
          </p>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); saveFolder(folder); }}>
            <Input id="out-dir" spellCheck={false} placeholder="Chưa chọn (chỉ lưu trong app)" value={folder}
              onChange={(e) => setFolder(e.target.value)} className="min-w-0 font-mono text-xs" />
            {desktopApi() && <Button type="button" variant="outline" onClick={pickFolder} disabled={savingFolder}>Chọn…</Button>}
            <Button type="submit" disabled={savingFolder || folder.trim() === (info?.output_dir ?? "")}>
              {savingFolder ? <Loader2 className="animate-spin" /> : null} Lưu
            </Button>
          </form>
          {info && info.output_suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {info.output_suggestions.map((s) => (
                <button key={s.path} type="button" title={s.path} disabled={savingFolder}
                  onClick={() => { setFolder(s.path); saveFolder(s.path); }}
                  className="rounded-full border px-2.5 py-1 text-xs hover:bg-accent">{s.label}</button>
              ))}
            </div>
          )}
          {info?.output_dir && (
            <button type="button" className="justify-self-start text-xs text-destructive underline underline-offset-2"
              disabled={savingFolder} onClick={() => saveFolder("")}>Tắt chép tự động</button>
          )}
        </div>

        {dl?.available && (
          <div className="grid gap-2 border-t pt-4">
            <Label className="flex items-center gap-1.5"><Mic className="size-4" /> Giọng VieNeu (chạy offline)</Label>
            {dl.ready ? (
              <p className="flex items-center gap-1.5 text-sm text-ok">
                <CheckCircle2 className="size-4" /> Đã tải. Chọn nhóm “VieNeu” trong danh sách giọng đọc.
              </p>
            ) : (
              <>
                <p className="text-xs text-muted-foreground">
                  25 giọng tiếng Việt Bắc, Trung, Nam chạy ngay trên máy, không cần mạng hay key, miễn phí.
                  Cần tải model một lần (~{dl.size_mb}MB). Nếu không bấm tải, app sẽ tự tải khi bạn xuất video với giọng VieNeu.
                </p>
                <div className="flex items-center gap-3">
                  <Button type="button" variant="outline" onClick={downloadVoices} disabled={dl.running}>
                    {dl.running ? <Loader2 className="animate-spin" /> : <Download />}
                    {dl.running ? `Đang tải${dl.progress != null ? ` ${Math.round(dl.progress * 100)}%` : "…"}` : "Tải model giọng"}
                  </Button>
                  {dl.error && <span className="text-xs text-destructive">{dl.error}</span>}
                </div>
              </>
            )}
            <p className="text-[11px] text-muted-foreground">
              Dùng VieNeu-TTS (Apache-2.0, pnnbao97/VieNeu-TTS). Âm thanh tạo ra được dùng cho video đăng công khai.
            </p>
          </div>
        )}

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
