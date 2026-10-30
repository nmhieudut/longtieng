"use client";

import { FileVideo, Film, Loader2, Play, Rocket, Trash2, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { StageBadge } from "@/components/project/stage-badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type Config, fmt, isActive, posterUrl, type ProjectSummary, upload } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] [&>*]:min-w-0">
      <NewProject />
      <ProjectList />
    </div>
  );
}

/** Only the import lives here. Language, voice and the rest are chosen inside the project, before it starts. */
function NewProject() {
  const router = useRouter();
  const [cfg, setCfg] = useState<Config | null>(null);
  const [over, setOver] = useState(false);
  const [msg, setMsg] = useState("");
  const [pct, setPct] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.config().then(setCfg).catch((e) => toast.error(e.message)); }, []);

  async function add(files: File[]) {
    if (!cfg || !files.length || pct !== null) return;
    let last: string | null = null;
    let ok = 0;
    const failed: string[] = [];
    for (const [i, f] of files.entries()) {
      setMsg(files.length > 1 ? `Đang tải lên ${i + 1}/${files.length}: ${f.name}` : `Đang tải lên ${f.name}`);
      setPct(0);
      try {
        if (f.size > cfg.max_upload_mb * 1048576) throw new Error(`lớn hơn ${cfg.max_upload_mb}MB`);
        last = (await upload(f, {}, setPct, false, false)).id;
        ok++;
      } catch (e) {
        failed.push(`${f.name}: ${(e as Error).message}`);
      }
    }
    setPct(null);
    setMsg("");
    if (failed.length) toast.error(`${failed.length} video lỗi:\n${failed.join("\n")}`);
    if (ok === 1 && files.length === 1 && last) { router.push(`/project?id=${last}`); return; }
    if (ok) {
      toast.success(`Đã thêm ${ok} video. Mở từng video để chọn ngôn ngữ, hoặc bấm “Bắt đầu tất cả”.`);
      window.dispatchEvent(new Event("projects-changed"));
    }
  }

  const busy = pct !== null;
  return (
    <Card className="self-start">
      <CardHeader>
        <CardTitle className="text-xl font-bold tracking-[-0.025em]">Nhập video</CardTitle>
        <CardDescription>Chọn một hoặc nhiều video. Ngôn ngữ và giọng đọc chọn trong từng dự án.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <button type="button" disabled={busy || !cfg} onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); add(Array.from(e.dataTransfer.files)); }}
          className={cn("flex w-full min-w-0 flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-input bg-muted/40 px-4 py-10 text-center transition-colors disabled:opacity-60",
            over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-accent")}>
          <span className="mb-1 grid size-12 place-items-center rounded-full bg-brand">
            {busy ? <Loader2 className="size-5 animate-spin" /> : <UploadCloud className="size-5" />}
          </span>
          <span className="font-medium">Kéo video vào đây hoặc bấm để chọn</span>
          <span className="text-xs text-muted-foreground">
            mp4, mov, webm, mkv{cfg && ` · tối đa ${cfg.max_upload_mb}MB · ${cfg.max_duration_min} phút`}
          </span>
        </button>
        <input ref={input} type="file" hidden multiple accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv,.m4v"
          onChange={(e) => { add(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
        {busy && (
          <div className="grid gap-1.5">
            <Progress value={(pct ?? 0) * 100} />
            <span className="flex items-center gap-1.5 truncate text-xs text-muted-foreground">
              <FileVideo className="size-3.5 shrink-0" /> <span className="truncate">{msg}</span> {Math.round((pct ?? 0) * 100)}%
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ProjectList() {
  const [list, setList] = useState<ProjectSummary[] | null>(null);
  const [autoRender, setAutoRender] = useState(false);
  const [starting, setStarting] = useState(false);

  const load = useCallback(() => {
    api.list().then(setList).catch((e) => toast.error(e.message));
  }, []);

  useEffect(() => {
    load();
    window.addEventListener("projects-changed", load);
    return () => window.removeEventListener("projects-changed", load);
  }, [load]);

  // refresh while anything is processing
  useEffect(() => {
    if (!list?.some((p) => isActive(p))) return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [list, load]);

  async function remove(p: ProjectSummary) {
    try {
      await api.remove(p.id);
      toast.success(`Đã xoá “${p.title}”`);
      load();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const fresh = (list ?? []).filter((p) => p.status.stage === "new");

  async function startAll() {
    setStarting(true);
    let ok = 0;
    const failed: string[] = [];
    for (const p of fresh) {
      try { await api.start(p.id, autoRender); ok++; } catch (e) { failed.push(`${p.title}: ${(e as Error).message}`); }
    }
    if (ok) toast.success(`Đã xếp ${ok} video vào hàng chờ${autoRender ? ", tự xuất khi xong" : ""}. Dùng ngôn ngữ và giọng của từng dự án.`);
    if (failed.length) toast.error(`${failed.length} video lỗi:\n${failed.join("\n")}`);
    setStarting(false);
    load();
  }

  return (
    <Card className="min-h-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4">
        <div className="mr-auto">
          <CardTitle className="text-xl font-bold tracking-[-0.025em]">Dự án</CardTitle>
          <CardDescription>{list ? `${list.length} video` : "Đang tải…"}</CardDescription>
        </div>
        {fresh.length > 0 && (
          <>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Switch checked={autoRender} onCheckedChange={setAutoRender} aria-label="Tự xuất video khi xử lý xong" /> Tự xuất
            </label>
            <Button variant="brand" size="lg" className="h-9 rounded-xl px-4" disabled={starting} onClick={startAll}>
              {starting ? <Loader2 className="animate-spin" /> : <Rocket />} Bắt đầu tất cả ({fresh.length})
            </Button>
          </>
        )}
      </div>
      <CardContent className="min-h-0 flex-1 overflow-y-auto">
        {!list ? (
          <div className="grid gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-input py-14 text-center text-muted-foreground">
            <Film className="size-8 text-primary/70" />
            <p>Chưa có dự án nào. Nhập video để bắt đầu.</p>
          </div>
        ) : (
          <ul className="-mx-2 flex flex-col gap-0.5">
            {list.map((p) => (
              <li key={p.id} className="group flex min-w-0 items-center gap-2 rounded-xl px-2 py-2 transition-colors hover:bg-accent/70 sm:gap-3">
                <Link href={`/project?id=${p.id}`} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                  <Poster key={`${p.id}-${p.duration ?? 0}`} id={p.id} ready={!!p.duration} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium" title={p.title}>{p.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {[
                        new Date(p.created * 1000).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" }),
                        p.duration ? fmt(p.duration) : null,
                        p.segments ? `${p.segments} câu` : null,
                      ].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </Link>
                <StageBadge stage={p.status.stage} hasFinal={p.has_final} progress={p.status.progress} />
                {p.status.stage === "new" && (
                  <IconButton label="Bắt đầu video này" variant="outline"
                    onClick={() => api.start(p.id, autoRender).then(load).catch((e) => toast.error(e.message))}><Play /></IconButton>
                )}
                <AlertDialog>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label="Xoá dự án" className="text-muted-foreground hover:text-destructive">
                          <Trash2 />
                        </Button>
                      </AlertDialogTrigger>
                    </TooltipTrigger>
                    <TooltipContent>Xoá dự án</TooltipContent>
                  </Tooltip>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Xoá “{p.title}”?</AlertDialogTitle>
                      <AlertDialogDescription>Video gốc, bản dịch và mọi file đã xuất của dự án sẽ bị xoá vĩnh viễn.</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Huỷ</AlertDialogCancel>
                      <AlertDialogAction variant="destructive" onClick={() => remove(p)}>Xoá</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/** Frame from the video; the film icon until the video is downloaded or if the frame can't be made. */
function Poster({ id, ready }: { id: string; ready: boolean }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="relative grid size-14 shrink-0 place-items-center overflow-hidden rounded-xl bg-secondary text-primary ring-1 ring-border transition-shadow group-hover:ring-2 group-hover:ring-primary/40">
      <Film className="size-5" />
      {ready && !failed && (
        // eslint-disable-next-line @next/next/no-img-element -- static export, served by the local app
        <img src={posterUrl(id)} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)}
          className="absolute inset-0 size-full object-cover" />
      )}
    </span>
  );
}
