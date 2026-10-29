"use client";

import { FileVideo, Film, Layers, Loader2, Trash2, UploadCloud, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { StageBadge } from "@/components/project/stage-badge";
import { VoicePicker } from "@/components/voice-picker";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Config, fmt, isActive, posterUrl, type ProjectSummary, upload } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <div className="grid gap-5 min-[900px]:grid-cols-[minmax(0,420px)_minmax(0,1fr)] min-[900px]:items-start xl:grid-cols-[minmax(0,480px)_minmax(0,1fr)] lg:gap-6 [&>*]:min-w-0">
      <NewProject />
      <ProjectList />
    </div>
  );
}

function NewProject() {
  const router = useRouter();
  const [cfg, setCfg] = useState<Config | null>(null);
  const [tab, setTab] = useState("file");
  const [file, setFile] = useState<File | null>(null);
  const [lang, setLang] = useState("zh");
  const [voice, setVoice] = useState("");
  const [over, setOver] = useState(false);
  const [sending, setSending] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [autoRender, setAutoRender] = useState(true);
  const [batchMsg, setBatchMsg] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const multi = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.config().then((c) => { setCfg(c); setVoice(c.defaults.voice); }).catch((e) => toast.error(e.message));
  }, []);

  async function startBatch() {
    if (!cfg) return;
    const settings = { lang, voice };
    if (!files.length) { toast.error("Chưa chọn video nào."); return; }
    setSending(true);
    let ok = 0;
    const failed: string[] = [];
    for (const [i, f] of files.entries()) {
      setBatchMsg(`Đang tải lên ${i + 1}/${files.length}: ${f.name}`);
      setPct(0);
      try {
        if (f.size > cfg.max_upload_mb * 1048576) throw new Error(`lớn hơn ${cfg.max_upload_mb}MB`);
        await upload(f, settings, setPct, autoRender);
        ok++;
      } catch (e) {
        failed.push(`${f.name}: ${(e as Error).message}`);
      }
    }
    setPct(null);
    setBatchMsg("");
    setSending(false);
    if (ok) {
      toast.success(`Đã xếp ${ok} video vào hàng chờ. App xử lý lần lượt từng video${autoRender ? " và tự xuất" : ""}.`);
      setFiles([]);
      window.dispatchEvent(new Event("projects-changed"));
    }
    if (failed.length) toast.error(`${failed.length} video lỗi:\n${failed.join("\n")}`);
  }

  async function start() {
    if (!cfg) return;
    if (tab === "batch") return startBatch();
    const settings = { lang, voice };
    setSending(true);
    try {
      if (!file) throw new Error("Chưa chọn video.");
      if (file.size > cfg.max_upload_mb * 1048576) throw new Error(`File lớn hơn ${cfg.max_upload_mb}MB.`);
      setPct(0);
      const p = await upload(file, settings, setPct);
      router.push(`/project?id=${p.id}`);
    } catch (e) {
      toast.error((e as Error).message);
      setSending(false);
      setPct(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl font-bold tracking-[-0.025em]">Video mới</CardTitle>
        <CardDescription>Nhận dạng giọng nói (Trung, Anh, Nhật, Hàn, Thái), dịch sang tiếng Việt và lồng tiếng tự động.</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-[minmax(0,1fr)] gap-5">
        <Tabs value={tab} onValueChange={setTab} className="min-w-0">
          <TabsList className="w-full">
            <TabsTrigger value="file" className="min-w-0"><UploadCloud /> <span className="truncate">Một video</span></TabsTrigger>
            <TabsTrigger value="batch" className="min-w-0"><Layers /> <span className="truncate">Nhiều video</span></TabsTrigger>
          </TabsList>
          <TabsContent value="batch" className="mt-3 grid gap-3">
            <button type="button" onClick={() => multi.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); setFiles((xs) => [...xs, ...Array.from(e.dataTransfer.files)]); }}
              className={cn("flex w-full min-w-0 flex-col items-center gap-1.5 rounded-xl border-[1.5px] border-dashed border-input bg-muted/40 px-4 py-6 text-center transition-colors",
                over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-accent")}>
              <Layers className="size-7 text-primary" />
              <span className="font-medium">Kéo nhiều video vào đây hoặc bấm để chọn</span>
              <span className="text-xs text-muted-foreground">Chọn được nhiều file cùng lúc</span>
            </button>
            <input ref={multi} type="file" hidden multiple
              accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv,.m4v"
              onChange={(e) => { setFiles((xs) => [...xs, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
            {files.length > 0 && (
              <ul className="grid max-h-40 gap-1 overflow-y-auto rounded-lg border p-1.5 text-sm">
                {files.map((f, i) => (
                  <li key={`${f.name}-${i}`} className="flex items-center gap-2 rounded px-1.5 py-1 hover:bg-muted">
                    <FileVideo className="size-4 shrink-0 text-primary" />
                    <span className="min-w-0 flex-1 truncate">{f.name}</span>
                    <span className="text-xs text-muted-foreground">{(f.size / 1048576).toFixed(0)}MB</span>
                    <button type="button" aria-label={`Bỏ ${f.name}`} onClick={() => setFiles((xs) => xs.filter((_, k) => k !== i))}
                      className="text-muted-foreground hover:text-destructive"><X className="size-4" /></button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex items-center justify-between gap-3 rounded-lg bg-muted/60 px-3 py-2">
              <div>
                <p className="text-sm font-medium">Tự lồng tiếng & xuất video</p>
                <p className="text-xs text-muted-foreground">Không cần duyệt bản dịch từng video.</p>
              </div>
              <Switch checked={autoRender} onCheckedChange={setAutoRender} />
            </div>
            <p className="text-xs text-muted-foreground">
              {cfg?.user_defaults
                ? "Mỗi video dùng ngôn ngữ, giọng bên dưới và cài đặt mặc định đã lưu (khung hình, logo, phụ đề, nhạc, lời thoại)."
                : "Mẹo: chỉnh khung hình, logo, phụ đề, nhạc ở một video rồi bấm “Lưu làm mặc định” để cả lô dùng chung."}
            </p>
          </TabsContent>
          <TabsContent value="file" className="mt-3">
            <button
              type="button"
              onClick={() => input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); setFile(e.dataTransfer.files[0] ?? null); }}
              className={cn(
                "flex w-full min-w-0 flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-input bg-muted/40 px-4 py-9 text-center transition-colors sm:py-11",
                over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-accent",
              )}
            >
              {file ? (
                <>
                  <FileVideo className="size-8 text-primary" />
                  <span className="block w-full truncate font-medium" title={file.name}>{file.name}</span>
                  <span className="text-xs text-muted-foreground">{(file.size / 1048576).toFixed(1)} MB · bấm để đổi file</span>
                </>
              ) : (
                <>
                  <span className="mb-1 grid size-12 place-items-center rounded-full bg-brand"><UploadCloud className="size-5" /></span>
                  <span className="font-medium">Kéo video vào đây hoặc bấm để chọn</span>
                  <span className="text-xs text-muted-foreground">
                    mp4, mov, webm{cfg && ` · tối đa ${cfg.max_upload_mb}MB · ${cfg.max_duration_min} phút`}
                  </span>
                </>
              )}
            </button>
            <input
              ref={input}
              type="file"
              hidden
              accept="video/mp4,video/quicktime,video/webm,video/x-matroska,.mkv,.m4v"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </TabsContent>
        </Tabs>

        <div className="grid gap-2">
          <Label>Ngôn ngữ gốc</Label>
          <Select value={lang} onValueChange={setLang}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(cfg?.langs ?? { zh: "Tiếng Trung" }).map(([k, label]) => (
                <SelectItem key={k} value={k}>{label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="grid gap-2">
          <Label>Giọng đọc <span className="font-normal text-muted-foreground">· bấm ▶ để nghe thử</span></Label>
          <VoicePicker voices={cfg?.voices ?? {}} value={voice} onChange={setVoice} className="max-h-72" />
        </div>

        {pct !== null && (
          <div className="grid gap-1.5">
            <Progress value={pct * 100} />
            <span className="truncate text-xs text-muted-foreground">{batchMsg || "Đang tải lên…"} {Math.round(pct * 100)}%</span>
          </div>
        )}
        {pct === null && batchMsg && <span className="text-xs text-muted-foreground">{batchMsg}</span>}

        <Button variant="brand" size="lg" className="h-11 rounded-xl text-[0.95rem]" disabled={sending || !cfg} onClick={start}>
          {sending ? <Loader2 className="animate-spin" /> : <Film />}
          {tab === "batch" ? `Bắt đầu ${files.length || ""} video`.replace("  ", " ") : "Bắt đầu"}
        </Button>
      </CardContent>
    </Card>
  );
}

function ProjectList() {
  const [list, setList] = useState<ProjectSummary[] | null>(null);

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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl font-bold tracking-[-0.025em]">Dự án</CardTitle>
        <CardDescription>{list ? `${list.length} video` : "Đang tải…"}</CardDescription>
      </CardHeader>
      <CardContent>
        {!list ? (
          <div className="grid gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border-[1.5px] border-dashed border-input py-14 text-center text-muted-foreground">
            <Film className="size-8 text-primary/70" />
            <p>Chưa có dự án nào. Thêm video ở bên trái để bắt đầu.</p>
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
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label="Xoá dự án" className="text-muted-foreground hover:text-destructive">
                      <Trash2 />
                    </Button>
                  </AlertDialogTrigger>
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
