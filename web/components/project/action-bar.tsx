"use client";

import {
  AlertTriangle, ArrowLeft, CheckCircle2, Clapperboard, Download, FileJson, FileText, FolderOpen, Info, Languages, Loader2, MoreHorizontal,
  Play, RotateCcw, Subtitles, Wand2, X,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { IconButton } from "@/components/ui/icon-button";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, desktopApi, fileUrl, fmt, isActive, type Project, STAGE_LABEL } from "@/lib/api";
import { cn } from "@/lib/utils";

import { StageBadge } from "./stage-badge";
import { Steps } from "./steps";

type Props = {
  project: Project & { edited_at?: number };
  previewAt: number;
  onStart: () => void;
  onPreview: () => void;
  onRender: () => void;
  onRetry: () => void;
  onRewrite: () => Promise<void>;
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

/** The one strip with everything you press: start, translate again, preview, export, download. Always on top. */
export function ActionBar({ project: p, previewAt, onStart, onPreview, onRender, onRetry, onRewrite, onCancel, onJump, onSaveToFolder }: Props) {
  const [stopping, setStopping] = useState(false);
  const [folder, setFolder] = useState("");
  const [copying, setCopying] = useState(false);
  const [askRewrite, setAskRewrite] = useState(false);
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
  const langStale = hasLines && (p.translated_to ?? "vi") !== p.settings.target;
  const cancelling = s.message === "Đang huỷ…";
  // no lines: the video is simply being edited. Translating and dubbing is an option, not a step you must take.
  const editOnly = !hasLines && (s.stage === "new" || s.stage === "done");

  const dl = (key: "final" | "srt" | "json" | "txt") => {
    const f = p.outputs[key];
    return f ? `${fileUrl(p.id, f.file)}?download=1&t=${f.at ?? ""}` : undefined;
  };
  const over = p.segments.findIndex((x) => x.vi.trim() && x.fit?.status === "overflow");
  const empty = p.segments.findIndex((x) => !x.vi.trim());
  const nOver = p.segments.filter((x) => x.vi.trim() && x.fit?.status === "overflow").length;
  const nEmpty = p.segments.filter((x) => !x.vi.trim()).length;
  const bridge = desktopApi();
  const saved = p.outputs.saved;

  const head = (
    <div className="flex min-w-0 items-center gap-2">
      <IconButton label="Về danh sách" href="/" variant="outline"><ArrowLeft /></IconButton>
      <h1 className="min-w-0 max-w-[28ch] truncate font-heading text-base font-bold tracking-[-0.02em]" title={p.title}>{p.title}</h1>
      <StageBadge stage={s.stage} hasFinal={!!final} progress={s.progress} />
    </div>
  );

  let middle: React.ReactNode = null;
  let actions: React.ReactNode = null;

  if (active) {
    middle = (
      <div className="grid min-w-0 flex-1 gap-1">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
          <span className="truncate font-medium">{s.message || STAGE_LABEL[s.stage]}</span>
          {s.progress != null && <span className="ml-auto font-mono text-xs text-muted-foreground">{Math.round(s.progress * 100)}%</span>}
        </div>
        {s.progress != null ? <Progress value={s.progress * 100} /> : (
          <div className="relative h-2 overflow-hidden rounded-full bg-primary/20">
            <div className="absolute inset-y-0 w-1/3 animate-[indet_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
          </div>
        )}
      </div>
    );
    actions = (
      <IconButton label={cancelling ? "Đang huỷ…" : "Huỷ"} variant="outline" className="text-destructive hover:text-destructive"
        disabled={stopping || cancelling}
        onClick={async () => { setStopping(true); try { await onCancel(); } finally { setStopping(false); } }}>
        {stopping || cancelling ? <Loader2 className="animate-spin" /> : <X />}
      </IconButton>
    );
  } else if (!hasLines && !editOnly) {
    middle = (
      <p className="flex min-w-0 flex-1 items-center gap-1.5 text-sm text-destructive" title={s.error || s.message}>
        <AlertTriangle className="size-4 shrink-0" /><span className="truncate">{s.error || s.message}</span>
      </p>
    );
    actions = s.stage === "error" ? <IconButton label="Thử lại" variant="outline" onClick={onRetry}><RotateCcw /></IconButton> : null;
  } else {
    middle = (
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        {final ? (
          <span className={cn("flex items-center gap-1.5 font-medium", stale ? "text-fast-foreground" : "text-ok")}>
            {stale ? <AlertTriangle className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
            {stale ? "Có thay đổi chưa xuất lại" : `Video đã xuất · ${fmt(p.media?.duration ?? 0)} · ${ago(final.at!)}`}
          </span>
        ) : <span className="font-medium">{editOnly ? "Chỉnh sửa rồi xuất luôn · dịch và lồng tiếng là tuỳ chọn" : "Sẵn sàng lồng tiếng"}</span>}
        {!s.error && s.message.startsWith("Đã huỷ") && <span className="text-muted-foreground">{s.message}</span>}
        {langStale && <span className="text-fast-foreground">Lời thoại chưa theo ngôn ngữ mới, bấm nút đũa phép để viết lại</span>}
        {nOver > 0 && (
          <button type="button" onClick={() => onJump(over)} className="rounded-md bg-over/10 px-2 py-0.5 font-medium text-over hover:bg-over/20">
            {nOver} câu tràn
          </button>
        )}
        {nEmpty > 0 && (
          <button type="button" onClick={() => onJump(empty)} className="rounded-md bg-muted px-2 py-0.5 text-muted-foreground hover:bg-muted/70">
            {nEmpty} câu chưa dịch
          </button>
        )}
      </div>
    );
    actions = (
      <>
        {p.warnings.length > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span tabIndex={0} className="inline-flex items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground" aria-label={`${p.warnings.length} lưu ý`}>
                <Info className="size-4" />{p.warnings.length}
              </span>
            </TooltipTrigger>
            <TooltipContent className="grid max-w-xs gap-1">{p.warnings.map((w) => <span key={w}>• {w}</span>)}</TooltipContent>
          </Tooltip>
        )}
        {editOnly ? (
          <IconButton label="Dịch & lồng tiếng (tuỳ chọn): nhận dạng giọng nói, dịch và đọc lại bằng giọng đã chọn" variant="outline" onClick={onStart}><Languages /></IconButton>
        ) : (
          <IconButton label="Viết lại lời thoại theo cài đặt hiện tại" variant={langStale ? "brand" : "outline"} onClick={() => setAskRewrite(true)}><Wand2 /></IconButton>
        )}
        <IconButton label={`Xem thử 30 giây từ ${fmt(previewAt)}`} variant="outline" onClick={onPreview}><Play /></IconButton>
        {final && <IconButton label="Tải video MP4" href={dl("final")} download variant={stale ? "outline" : "secondary"}><Download /></IconButton>}
        <DropdownMenu>
          <Tooltip>
            <TooltipTrigger asChild>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon-sm" aria-label="Thêm"><MoreHorizontal /></Button>
              </DropdownMenuTrigger>
            </TooltipTrigger>
            <TooltipContent>Tải thêm, thư mục lưu</TooltipContent>
          </Tooltip>
          <DropdownMenuContent align="end">
            {p.outputs.srt && <DropdownMenuItem asChild><a href={dl("srt")}><Subtitles /> Phụ đề .srt</a></DropdownMenuItem>}
            {p.outputs.txt && <DropdownMenuItem asChild><a href={dl("txt")}><FileText /> Transcript .txt</a></DropdownMenuItem>}
            {p.outputs.json && <DropdownMenuItem asChild><a href={dl("json")}><FileJson /> Transcript .json</a></DropdownMenuItem>}
            {final && folder && (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={copying}
                  onSelect={async () => { setCopying(true); try { await onSaveToFolder(); } finally { setCopying(false); } }}>
                  {copying ? <Loader2 className="animate-spin" /> : <FolderOpen />} Chép vào thư mục đã chọn
                </DropdownMenuItem>
              </>
            )}
            {saved?.path && bridge && (
              <DropdownMenuItem onSelect={() => bridge.reveal(saved.path!)}><FolderOpen /> Mở thư mục đã chép</DropdownMenuItem>
            )}
            {!p.outputs.srt && !p.outputs.txt && !p.outputs.json && !(final && folder) && (
              <DropdownMenuItem disabled>Chưa có gì để tải</DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button variant="brand" size="lg" className="h-9 rounded-xl px-4" onClick={onRender}>
          {final ? <RotateCcw /> : <Clapperboard />} {final ? "Xuất lại" : "Xuất video"}
        </Button>
      </>
    );
  }

  const note = !active && (hasLines || editOnly) ? (s.error ? s.error : saved?.error ? saved.error : null) : null;

  return (
    <header className="shrink-0 rounded-2xl border bg-card px-3 py-2 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {head}
        {(hasLines || active) && <div className="hidden lg:block"><Steps project={p} /></div>}
        <div className="flex min-w-[220px] flex-1 items-center">{middle}</div>
        <div className="ml-auto flex items-center gap-1.5">{actions}</div>
      </div>
      {note && (
        <p className="mt-2 flex gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-1.5 text-xs text-destructive">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /><span className="min-w-0 whitespace-pre-wrap break-words">{note}</span>
        </p>
      )}
      {saved?.path && !active && (
        <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground" title={saved.path}>
          <FolderOpen className="size-3 shrink-0 text-primary" /><span className="min-w-0 truncate">Đã chép vào {saved.path}</span>
        </p>
      )}
      <AlertDialog open={askRewrite} onOpenChange={setAskRewrite}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Viết lại toàn bộ lời thoại?</AlertDialogTitle>
            <AlertDialogDescription>
              Các câu bạn đã sửa tay sẽ bị thay bằng bản dịch mới theo ngôn ngữ và chế độ trong tab “Ngôn ngữ”.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Giữ nguyên</AlertDialogCancel>
            <AlertDialogAction onClick={() => { void onRewrite(); }}>Viết lại</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </header>
  );
}
