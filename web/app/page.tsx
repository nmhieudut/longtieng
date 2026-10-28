"use client";

import { FileVideo, Film, Layers, Link2, Loader2, Trash2, UploadCloud, X } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Config, fmt, isActive, type ProjectSummary, upload } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function Home() {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,520px)_1fr] lg:items-start">
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
  const [url, setUrl] = useState("");
  const [lang, setLang] = useState("zh");
  const [voice, setVoice] = useState("");
  const [over, setOver] = useState(false);
  const [sending, setSending] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [links, setLinks] = useState("");
  const [autoRender, setAutoRender] = useState(true);
  const [batchMsg, setBatchMsg] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const multi = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.config().then((c) => { setCfg(c); setVoice(c.defaults.voice); }).catch((e) => toast.error(e.message));
  }, []);

  const linkList = links.split(/\s+/).map((x) => x.trim()).filter((x) => /^https?:\/\//.test(x));

  async function startBatch() {
    if (!cfg) return;
    const settings = { lang, voice };
    const total = files.length + linkList.length;
    if (!total) { toast.error("Chưa chọn video hoặc dán link nào."); return; }
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
    for (const [i, u] of linkList.entries()) {
      setBatchMsg(`Đang thêm link ${i + 1}/${linkList.length}`);
      try {
        await api.fromUrl(u, settings, autoRender);
        ok++;
      } catch (e) {
        failed.push(`${u}: ${(e as Error).message}`);
      }
    }
    setBatchMsg("");
    setSending(false);
    if (ok) {
      toast.success(`Đã xếp ${ok} video vào hàng chờ. App xử lý lần lượt từng video${autoRender ? " và tự xuất" : ""}.`);
      setFiles([]);
      setLinks("");
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
      let p;
      if (tab === "file") {
        if (!file) throw new Error("Chưa chọn video.");
        if (file.size > cfg.max_upload_mb * 1048576) throw new Error(`File lớn hơn ${cfg.max_upload_mb}MB.`);
        setPct(0);
        p = await upload(file, settings, setPct);
      } else {
        if (!url.trim()) throw new Error("Chưa dán link.");
        p = await api.fromUrl(url.trim(), settings);
      }
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
        <CardTitle className="text-lg">Video mới</CardTitle>
        <CardDescription>Nhận dạng giọng nói (Trung, Anh, Nhật, Hàn, Thái), dịch sang tiếng Việt và lồng tiếng tự động.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="w-full">
            <TabsTrigger value="file"><UploadCloud /> Tải file lên</TabsTrigger>
            <TabsTrigger value="url"><Link2 /> Dán link</TabsTrigger>
            <TabsTrigger value="batch"><Layers /> Nhiều video</TabsTrigger>
          </TabsList>
          <TabsContent value="batch" className="mt-3 grid gap-3">
            <button type="button" onClick={() => multi.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); setFiles((xs) => [...xs, ...Array.from(e.dataTransfer.files)]); }}
              className={cn("flex w-full flex-col items-center gap-1.5 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors",
                over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-muted/60")}>
              <Layers className="size-7 text-muted-foreground" />
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
            <Textarea rows={3} placeholder={"Hoặc dán nhiều link, mỗi link một dòng\nhttps://www.youtube.com/…\nhttps://www.tiktok.com/…"}
              value={links} onChange={(e) => setLinks(e.target.value)} />
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
                "flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors",
                over ? "border-primary bg-primary/5" : "hover:border-primary/60 hover:bg-muted/60",
              )}
            >
              {file ? (
                <>
                  <FileVideo className="size-8 text-primary" />
                  <span className="max-w-full truncate font-medium">{file.name}</span>
                  <span className="text-xs text-muted-foreground">{(file.size / 1048576).toFixed(1)} MB · bấm để đổi file</span>
                </>
              ) : (
                <>
                  <UploadCloud className="size-8 text-muted-foreground" />
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
          <TabsContent value="url" className="mt-3 grid gap-2">
            <Input
              type="url"
              placeholder="https://www.douyin.com/… hoặc YouTube, TikTok, Bilibili"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && start()}
            />
            <p className="text-xs text-muted-foreground">
              Douyin hay chặn tải tự động. Nếu lỗi, tải video về máy rồi dùng “Tải file lên”.
            </p>
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

        <Button size="lg" className="h-10" disabled={sending || !cfg} onClick={start}>
          {sending ? <Loader2 className="animate-spin" /> : <Film />}
          {tab === "batch" ? `Bắt đầu ${files.length + linkList.length || ""} video`.replace("  ", " ") : "Bắt đầu"}
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
        <CardTitle className="text-lg">Dự án</CardTitle>
        <CardDescription>{list ? `${list.length} video` : "Đang tải…"}</CardDescription>
      </CardHeader>
      <CardContent>
        {!list ? (
          <div className="grid gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-12 text-center text-muted-foreground">
            <Film className="size-8" />
            <p>Chưa có dự án nào. Thêm video ở bên trái để bắt đầu.</p>
          </div>
        ) : (
          <ul className="divide-y">
            {list.map((p) => (
              <li key={p.id} className="group flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <Link href={`/project?id=${p.id}`} className="flex min-w-0 flex-1 items-center gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary">
                    <Film className="size-5" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium group-hover:text-primary">{p.title}</span>
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
