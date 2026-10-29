"use client";

import {
  AlertTriangle, CheckCircle2, ChevronDown, Clapperboard, Download, FileJson, FileText, FolderOpen, Info, Loader2, Play,
  RotateCcw, Subtitles, X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Progress } from "@/components/ui/progress";
import { api, desktopApi, fileUrl, fmt, isActive, type Project, STAGE_LABEL } from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  project: Project & { edited_at?: number };
  previewAt: number;
  onPreview: () => void;
  onRender: () => void;
  onRetry: () => void;
  onCancel: () => Promise<void>;
  onJump: (segIndex: number) => void;   // show a problem line in the list
  onSaveToFolder: () => Promise<void>;
};

const ago = (t: number) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "vừa xong";
  if (s < 3600) return `${Math.floor(s / 60)} phút trước`;
  if (s < 86400) return `${Math.floor(s / 3600)} giờ trước`;
  return new Date(t * 1000).toLocaleDateString("vi-VN");
};

export function ExportPanel({ project: p, previewAt, onPreview, onRender, onRetry, onCancel, onJump, onSaveToFolder }: Props) {
  const [stopping, setStopping] = useState(false);
  const [folder, setFolder] = useState("");
  const [copying, setCopying] = useState(false);
  useEffect(() => {
    const load = () => { api.appSettings().then((i) => setFolder(i.output_dir)).catch(() => {}); };
    load();
    window.addEventListener("app-settings-changed", load);
    return () => window.removeEventListener("app-settings-changed", load);
  }, []);
  const s = p.status;
  const active = isActive(p);
  const hasLines = p.segments.length > 0;
  const final = p.outputs.final;
  const stale = !!final?.at && !!p.edited_at && p.edited_at > final.at;

  const dl = (key: "preview" | "final" | "srt" | "json" | "txt") => {
    const f = p.outputs[key];
    return f ? `${fileUrl(p.id, f.file)}?download=1&t=${f.at ?? ""}` : undefined;
  };

  // ---- 1. working
  if (active) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <div className="flex items-center gap-2 text-sm">
            <Loader2 className="size-4 animate-spin text-primary" />
            <span className="font-medium">{s.message || STAGE_LABEL[s.stage]}</span>
            {s.progress != null && <span className="ml-auto font-mono text-xs text-muted-foreground">{Math.round(s.progress * 100)}%</span>}
          </div>
          {s.progress != null ? (
            <Progress value={s.progress * 100} />
          ) : (
            <div className="relative h-2 overflow-hidden rounded-full bg-primary/20">
              <div className="absolute inset-y-0 w-1/3 animate-[indet_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
            </div>
          )}
          <Button
            variant="outline"
            className="justify-self-start text-destructive hover:text-destructive"
            disabled={stopping || s.message === "Đang huỷ…"}
            onClick={async () => { setStopping(true); try { await onCancel(); } finally { setStopping(false); } }}
          >
            {stopping || s.message === "Đang huỷ…" ? <Loader2 className="animate-spin" /> : <X />}
            {s.message === "Đang huỷ…" ? "Đang huỷ…" : "Huỷ"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // ---- 2. failed before there was anything to edit
  if (!hasLines) {
    return (
      <Card>
        <CardContent className="grid gap-3">
          <ErrorBox message={s.error || s.message} />
          {s.stage === "error" && <Button variant="outline" onClick={onRetry}><RotateCcw /> Thử lại</Button>}
        </CardContent>
      </Card>
    );
  }

  // ---- 3. ready / exported
  const over = p.segments.findIndex((x) => x.vi.trim() && x.fit?.status === "overflow");
  const empty = p.segments.findIndex((x) => !x.vi.trim());
  const nOver = p.segments.filter((x) => x.vi.trim() && x.fit?.status === "overflow").length;
  const nEmpty = p.segments.filter((x) => !x.vi.trim()).length;

  return (
    <Card>
      <CardContent className="grid gap-4">
        {s.error && <ErrorBox message={s.error} />}
        {!s.error && s.message.startsWith("Đã huỷ") && (
          <p className="flex items-center gap-1.5 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            <X className="size-3.5" /> {s.message}
          </p>
        )}

        {final ? (
          <div className="flex items-center gap-3">
            <span className={cn("grid size-9 shrink-0 place-items-center rounded-full",
              stale ? "bg-fast/20 text-fast-foreground" : "bg-ok/15 text-ok")}>
              {stale ? <AlertTriangle className="size-4" /> : <CheckCircle2 className="size-4" />}
            </span>
            <div className="min-w-0">
              <p className="font-medium">{stale ? "Có thay đổi chưa xuất lại" : "Video đã xuất"}</p>
              <p className="text-xs text-muted-foreground">
                {stale ? "Bản đã xuất chưa có các chỉnh sửa mới." : `${fmt(p.media?.duration ?? 0)} · ${ago(final.at!)}`}
              </p>
            </div>
          </div>
        ) : (
          <div>
            <p className="font-medium">Sẵn sàng lồng tiếng</p>
            <p className="text-xs text-muted-foreground">Kiểm tra bản dịch bên phải, rồi xuất video.</p>
          </div>
        )}

        {(nOver > 0 || nEmpty > 0) && (
          <div className="flex flex-wrap gap-2 text-xs">
            {nOver > 0 && (
              <button type="button" onClick={() => onJump(over)}
                className="rounded-md bg-over/10 px-2 py-1 font-medium text-over hover:bg-over/20">
                {nOver} câu tràn, sẽ bị cắt · xem
              </button>
            )}
            {nEmpty > 0 && (
              <button type="button" onClick={() => onJump(empty)}
                className="rounded-md bg-muted px-2 py-1 text-muted-foreground hover:bg-muted/70">
                {nEmpty} câu chưa dịch · xem
              </button>
            )}
          </div>
        )}

        {final ? (
          <div className="grid gap-2">
            <div className="flex gap-2">
              <Button asChild size="lg" variant={stale ? "outline" : "brand"} className="h-10 flex-1">
                <a href={dl("final")}><Download /> Tải video MP4</a>
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="lg" variant="outline" className="h-10">Tải thêm <ChevronDown /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {p.outputs.srt && <DropdownMenuItem asChild><a href={dl("srt")}><Subtitles /> Phụ đề .srt</a></DropdownMenuItem>}
                  {p.outputs.txt && <DropdownMenuItem asChild><a href={dl("txt")}><FileText /> Transcript .txt</a></DropdownMenuItem>}
                  {p.outputs.json && <DropdownMenuItem asChild><a href={dl("json")}><FileJson /> Transcript .json</a></DropdownMenuItem>}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <SavedCopyRow saved={p.outputs.saved} folder={folder} copying={copying}
              onCopy={async () => { setCopying(true); try { await onSaveToFolder(); } finally { setCopying(false); } }} />
            <div className="flex gap-2">
              <Button variant={stale ? "brand" : "outline"} className="flex-1" onClick={onRender}>
                <RotateCcw /> Xuất lại
              </Button>
              <Button variant="ghost" className="flex-1" onClick={onPreview}>
                <Play /> Xem thử 30s từ {fmt(previewAt)}
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid gap-2">
            <Button variant="brand" size="lg" className="h-11 rounded-xl text-base" onClick={onRender}>
              <Clapperboard /> Lồng tiếng & xuất video
            </Button>
            <Button variant="ghost" onClick={onPreview}>
              <Play /> Xem thử 30s từ {fmt(previewAt)}
            </Button>
          </div>
        )}

        {p.warnings.length > 0 && <Notes items={p.warnings} />}
      </CardContent>
    </Card>
  );
}

/** Where the folder copy of the export is, or a button to make one. */
function SavedCopyRow({ saved, folder, copying, onCopy }: {
  saved: Project["outputs"]["saved"]; folder: string; copying: boolean; onCopy: () => void;
}) {
  const bridge = desktopApi();
  if (saved?.path) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs">
        <FolderOpen className="size-3.5 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 break-all text-muted-foreground" title={saved.path}>Đã chép vào {saved.path}</span>
        {bridge && (
          <button type="button" className="shrink-0 font-medium text-primary hover:underline" onClick={() => bridge.reveal(saved.path!)}>
            Mở thư mục
          </button>
        )}
      </div>
    );
  }
  if (!folder) return saved?.error ? <ErrorBox message={saved.error} /> : null;
  return (
    <>
      {saved?.error && <ErrorBox message={saved.error} />}
      <Button variant="outline" disabled={copying} onClick={onCopy} title={folder}>
        {copying ? <Loader2 className="animate-spin" /> : <FolderOpen />} Chép vào thư mục đã chọn
      </Button>
    </>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <p className="min-w-0 whitespace-pre-wrap break-words">{message}</p>
    </div>
  );
}

function Notes({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="text-xs text-muted-foreground">
      <button type="button" onClick={() => setOpen((x) => !x)} className="flex items-center gap-1.5 hover:text-foreground">
        <Info className="size-3.5" /> {items.length} lưu ý <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && <ul className="mt-1.5 list-disc space-y-1 pl-5">{items.map((w) => <li key={w}>{w}</li>)}</ul>}
    </div>
  );
}
