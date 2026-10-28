"use client";

import { ArrowLeft, Languages, Send, SlidersHorizontal, WifiOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, type Config, type DeepPartial, fileUrl, isActive, type Project, type Settings } from "@/lib/api";

import { SegmentList } from "./segment-list";
import { SettingsPanel } from "./settings-panel";
import { StageBadge } from "./stage-badge";
import { ExportPanel } from "./export-panel";
import { Steps } from "./steps";
import { useProject } from "./use-project";
import { PublishPanel } from "./publish-panel";
import { VideoPanel, type VideoView } from "./video-panel";

export function ProjectView({ id }: { id: string }) {
  const { project: p, error, apply, offline } = useProject(id);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [view, setView] = useState<VideoView>("source");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tab, setTab] = useState("lines");
  const [draft, setDraft] = useState<Settings | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingShow = useRef<"preview" | "final" | null>(null);
  const pendingSeek = useRef<number | null>(null);
  const seenOutputs = useRef<Project["outputs"] | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => { api.config().then(setCfg).catch(() => {}); }, []);

  // when a render we asked for finishes, show it
  useEffect(() => {
    if (!p) return;
    const prev = seenOutputs.current;
    seenOutputs.current = p.outputs;
    const want = pendingShow.current;
    if (prev && want && p.outputs[want] && p.outputs[want]?.at !== prev[want]?.at) {
      pendingShow.current = null;
      setView(want);
    }
  }, [p]);

  const src = useMemo(() => {
    const file = p?.source.file;
    if (!p || !file) return null;
    const o = view === "source" ? undefined : p.outputs[view];
    return o ? fileUrl(p.id, o.file, o.at) : fileUrl(p.id, file);
  }, [p, view]);

  // keep position when switching between the original and the dubbed video (same timeline)
  const keepTime = useRef(0);
  const changeView = useCallback((v: VideoView) => {
    keepTime.current = view !== "preview" && v !== "preview" ? (videoRef.current?.currentTime ?? 0) : 0;
    setView(v);
  }, [view]);

  const onLoaded = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    const t = pendingSeek.current ?? keepTime.current;
    pendingSeek.current = null;
    keepTime.current = 0;
    if (t) v.currentTime = t;
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const on = () => setPlaying(!v.paused);
    v.addEventListener("play", on);
    v.addEventListener("pause", on);
    return () => { v.removeEventListener("play", on); v.removeEventListener("pause", on); };
  }, [src]);

  const seek = useCallback((t: number) => {
    if (view === "preview") {
      pendingSeek.current = t;
      setView("source");
      return;
    }
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setTime(t);
  }, [view]);

  const activeIdx = useMemo(() => {
    if (!p || view === "preview") return -1;
    let idx = -1;
    for (let i = 0; i < p.segments.length; i++) {
      if (p.segments[i].start <= time) idx = i;
      else break;
    }
    return idx;
  }, [p, time, view]);

  const run = useCallback(async (fn: () => Promise<Project>) => {
    try { apply(await fn()); }
    catch (e) { toast.error((e as Error).message); }
  }, [apply]);

  const onSave = useCallback((sid: number, vi: string) => run(() => api.editLine(id, sid, vi)), [id, run]);
  const onSettings = useCallback((patch: DeepPartial<Settings>) => run(() => api.settings(id, patch)), [id, run]);

  const onPlay = useCallback((sid: number) => {
    const seg = p?.segments.find((s) => s.id === sid);
    if (!seg?.tts) return;
    audio.current?.pause();
    videoRef.current?.pause();
    audio.current = new Audio(fileUrl(id, seg.tts.file, seg.tts.ver));
    audio.current.play().catch(() => {});
  }, [p, id]);

  const onRegen = useCallback(async (sid: number) => {
    try {
      const np = await api.lineTts(id, sid);
      apply(np);
      const seg = np.segments.find((s) => s.id === sid);
      if (seg?.tts) {
        audio.current?.pause();
        audio.current = new Audio(fileUrl(id, seg.tts.file, seg.tts.ver));
        audio.current.play().catch(() => {});
      }
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [id, apply]);

  if (error) {
    return (
      <div className="grid place-items-center gap-3 py-24 text-center">
        <p className="text-destructive">{error}</p>
        <Link href="/" className="text-sm text-primary hover:underline">← Về danh sách</Link>
      </div>
    );
  }
  if (!p) return <LoadingSkeleton />;

  const busy = isActive(p);
  const settings = draft ?? p.settings;
  const previewAt = view === "preview" ? 0 : time;

  return (
    <div className="grid gap-5">
      {offline && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <WifiOff className="size-4 shrink-0" />
          Mất kết nối tới server. Kiểm tra server còn chạy không (uv run python -m app). Trang sẽ tự kết nối lại.
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <Link href="/" aria-label="Về danh sách" className="grid size-8 place-items-center rounded-lg border bg-background hover:bg-muted">
          <ArrowLeft className="size-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold">{p.title}</h1>
        </div>
        <StageBadge stage={p.status.stage} hasFinal={!!p.outputs.final} progress={p.status.progress} />
        <div className="w-full sm:w-auto"><Steps project={p} /></div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(340px,460px)_1fr] lg:items-start">
        <div className="grid min-w-0 gap-5">
          <Card className="p-3">
            <VideoPanel
              project={p}
              videoRef={videoRef}
              src={src}
              view={view}
              onView={changeView}
              time={time}
              activeIdx={activeIdx}
              mask={settings.mask}
              onSeek={seek}
              onTime={setTime}
              onLoaded={onLoaded}
            />
          </Card>
          <ExportPanel
            project={p}
            previewAt={previewAt}
            onRetry={() => run(() => api.retry(id))}
            onCancel={() => run(() => api.cancel(id))}
            onPreview={() => { pendingShow.current = "preview"; run(() => api.render(id, previewAt)); }}
            onRender={() => { pendingShow.current = "final"; run(() => api.render(id, null)); }}
            onJump={(i) => {
              setTab("lines");
              seek(p.segments[i].start + 0.01);
              setTimeout(() => {
                const row = document.querySelector<HTMLElement>(`[data-idx="${i}"]`);
                row?.scrollIntoView({ block: "center", behavior: "smooth" });
                row?.querySelector("textarea")?.focus({ preventScroll: true });
              }, 60);
            }}
          />
        </div>

        <Card className="min-w-0 gap-0 overflow-hidden p-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)]">
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-0">
            <div className="border-b px-4 py-3">
              <TabsList className="w-full sm:w-auto">
                <TabsTrigger value="lines"><Languages /> Bản dịch{p.segments.length ? ` (${p.segments.length})` : ""}</TabsTrigger>
                <TabsTrigger value="settings"><SlidersHorizontal /> Cài đặt</TabsTrigger>
                <TabsTrigger value="publish"><Send /> Đăng Reels</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="lines" className="min-h-0 flex-1 overflow-y-auto">
              <SegmentList
                project={p}
                activeIdx={activeIdx}
                playing={playing}
                onSeek={seek}
                onSave={onSave}
                onRegen={onRegen}
                onPlay={onPlay}
              />
            </TabsContent>
            <TabsContent value="settings" className="min-h-0 flex-1 overflow-y-auto">
              <SettingsPanel
                settings={p.settings}
                voices={cfg?.voices ?? {}}
                disabled={busy}
                onDraft={setDraft}
                onSave={async (patch) => { await onSettings(patch); setDraft(null); }}
                maskDetect={p.mask_detect}
                onDetect={async () => {
                  await run(async () => {
                    const np = await api.detectMask(id);
                    toast.success(np.mask_detect?.found ? "Đã tìm thấy và che vùng phụ đề Trung." : "Không thấy phụ đề Trung trên video.");
                    return np;
                  });
                  setDraft(null);
                }}
              />
            </TabsContent>
            <TabsContent value="publish" className="min-h-0 flex-1 overflow-y-auto">
              <PublishPanel project={p} time={view === "preview" ? 0 : time} apply={apply} />
            </TabsContent>
          </Tabs>
        </Card>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-5">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-5 lg:grid-cols-[minmax(340px,460px)_1fr]">
        <div className="grid gap-5"><Skeleton className="aspect-[9/12]" /><Skeleton className="h-40" /></div>
        <Skeleton className="h-[70vh]" />
      </div>
    </div>
  );
}
