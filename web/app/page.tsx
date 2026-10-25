"use client";

import { FileVideo, Film, Link2, Loader2, Trash2, UploadCloud } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
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
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.config().then((c) => { setCfg(c); setVoice(c.defaults.voice); }).catch((e) => toast.error(e.message));
  }, []);

  async function start() {
    if (!cfg) return;
    const settings = { lang: lang as "zh" | "auto", voice };
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
        <CardDescription>Nhận dạng tiếng Trung, dịch sang tiếng Việt và lồng tiếng tự động.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="w-full">
            <TabsTrigger value="file"><UploadCloud /> Tải file lên</TabsTrigger>
            <TabsTrigger value="url"><Link2 /> Dán link</TabsTrigger>
          </TabsList>
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

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label>Ngôn ngữ gốc</Label>
            <Select value={lang} onValueChange={setLang}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="zh">Tiếng Trung</SelectItem>
                <SelectItem value="auto">Tự nhận diện</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label>Giọng đọc</Label>
            <Select value={voice} onValueChange={setVoice}>
              <SelectTrigger className="w-full"><SelectValue placeholder="…" /></SelectTrigger>
              <SelectContent>
                {cfg && Object.entries(cfg.voices).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        {pct !== null && (
          <div className="grid gap-1.5">
            <Progress value={pct * 100} />
            <span className="text-xs text-muted-foreground">Đang tải lên… {Math.round(pct * 100)}%</span>
          </div>
        )}

        <Button size="lg" className="h-10" disabled={sending || !cfg} onClick={start}>
          {sending ? <Loader2 className="animate-spin" /> : <Film />}
          Bắt đầu
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

  useEffect(() => { load(); }, [load]);

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
