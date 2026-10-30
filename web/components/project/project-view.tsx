"use client";

import { AudioLines, Captions, EyeOff, Frame, ImageIcon, Languages, Mic, Music, Palette, Send, Sparkles, WifiOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Card } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Config, type DeepPartial, fileUrl, isActive, type Project, type Settings } from "@/lib/api";

import { SegmentList } from "./segment-list";
import { SECTION_IDS, type SectionId, SettingsPanel, type SettingsHandle } from "./settings-panel";
import { ActionBar } from "./action-bar";
import { useProject } from "./use-project";
import { PublishPanel } from "./publish-panel";
import { TimelinePanel } from "./timeline-panel";
import { useClipPlayback } from "./use-clip-playback";
import { newEditLog } from "./edit-log";
import { useOverlays } from "./use-overlays";
import { locate, mapLines, totalLen } from "@/lib/timeline";
import { useTimeline } from "./use-timeline";
import { VideoPanel, type VideoView } from "./video-panel";

// the timeline hooks must run before the "still loading" early return; they never save without a real project
const NO_PROJECT = { id: "", media: null, segments: [] } as unknown as Project;

export function ProjectView({ id }: { id: string }) {
  const { project: p, error, apply, offline } = useProject(id);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [view, setView] = useState<VideoView>("source");
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [tabSel, setTab] = useState<string | null>(null);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const settingsRef = useRef<SettingsHandle>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingShow = useRef<"preview" | "final" | null>(null);
  const pendingSeek = useRef<number | null>(null);
  const autoplayNext = useRef(false);
  const [playSrc, setPlaySrc] = useState(0);   // which video file the player has loaded (0 = the main one)
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

  // a video that was removed from the project can no longer be the loaded one
  const loadedSrc = !p || playSrc === 0 || p.extra_sources?.some((e) => e.id === playSrc) ? playSrc : 0;
  const src = useMemo(() => {
    const file = loadedSrc === 0 ? p?.source.file : p?.extra_sources?.find((e) => e.id === loadedSrc)?.file;
    if (!p || !file) return null;
    const o = view === "source" ? undefined : p.outputs[view];
    return o ? fileUrl(p.id, o.file, o.at) : fileUrl(p.id, file);
  }, [p, view, loadedSrc]);

  // ---- timeline (cut / split / reorder / duplicate): the video element plays only the kept parts
  const onTimelineError = useCallback((m: string) => toast.error(m), []);
  const [editLog] = useState(newEditLog);
  const tl = useTimeline(p ?? NO_PROJECT, apply, onTimelineError, editLog);
  const overlays = useOverlays(p ?? NO_PROJECT, apply, onTimelineError, editLog);
  const jump = useCallback((t: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setTime(t);
  }, []);
  // another video file is needed: load it, and go to `t` (and keep playing) once it has loaded
  const switchTo = useCallback((srcId: number, t: number, autoplay: boolean) => {
    pendingSeek.current = t;
    autoplayNext.current = autoplay;
    setPlaySrc(srcId);
    setTime(t);
  }, []);
  const clipPlay = useClipPlayback({
    videoRef, clips: tl.clips, loaded: loadedSrc, active: view === "source" && tl.edited, playing, time, volume, muted,
    onJump: jump, onSwitch: switchTo,
  });
  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (v) { if (v.paused) v.play().catch(() => {}); else v.pause(); }
  }, []);

  // keep position when switching between the original and the dubbed video (same timeline)
  const keepTime = useRef(0);
  const changeView = useCallback((v: VideoView) => {
    const here = videoRef.current?.currentTime ?? 0;
    if (tl.edited && view !== "preview" && v !== "preview" && view !== v) {
      // original <-> exported: one is in source time, the other in output time
      if (view === "source") keepTime.current = clipPlay.T;
      else {
        const at = locate(tl.clips, here);
        pendingSeek.current = at.src;
        setPlaySrc(tl.clips[at.idx]?.src ?? 0);
      }
    } else {
      keepTime.current = view !== "preview" && v !== "preview" && loadedSrc === 0 ? here : 0;
    }
    setView(v);
  }, [view, loadedSrc, tl.edited, tl.clips, clipPlay.T]);

  const onLoaded = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    const t = pendingSeek.current ?? keepTime.current;
    pendingSeek.current = null;
    keepTime.current = 0;
    if (t) v.currentTime = t;
    if (autoplayNext.current) {
      autoplayNext.current = false;
      v.play().catch(() => {});
    }
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

  /** Go to second `t` of video `srcId`, loading that video first if another one is showing. */
  const seekAt = useCallback((srcId: number, t: number) => {
    if (view === "source" && srcId !== loadedSrc) { switchTo(srcId, t, false); return; }
    if (view !== "source" && srcId !== loadedSrc) { pendingSeek.current = t; setPlaySrc(srcId); setView("source"); return; }
    seek(t);
  }, [view, loadedSrc, switchTo, seek]);

  const activeIdx = useMemo(() => {
    if (!p || view === "preview") return -1;
    if (view === "final" && tl.edited) {
      // the exported video is the edited one: `time` is output time, so compare with where each line landed
      const placed = mapLines(tl.clips, p.segments.map((s, i) => ({ ...s, i })));
      let idx = -1;
      for (const l of placed) if (l.out0 <= time && l.out1 > time - 0.01) idx = l.i;
      return idx;
    }
    let idx = -1;
    for (let i = 0; i < p.segments.length; i++) {
      if ((p.segments[i].src_id ?? 0) === loadedSrc && p.segments[i].start <= time) idx = i;
    }
    return idx;
  }, [p, time, view, loadedSrc, tl.edited, tl.clips]);

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
  const previewAt = view === "preview" || loadedSrc !== 0 ? 0 : time;   // main video time (still preview, cover)
  const outAt = view === "preview" ? 0 : tl.edited && view === "source" ? clipPlay.T : time;  // output time (30 s preview)
  const fresh = p.status.stage === "new" && p.segments.length === 0;
  const tab = tabSel ?? (fresh ? "script" : "lines");
  const locked = busy && RENDER_STAGES.includes(p.status.stage);
  const sectionTab = (SECTION_IDS as readonly string[]).includes(tab) ? (tab as SectionId) : null;
  const flushAll = async () => {
    const a = document.activeElement;
    if (a instanceof HTMLTextAreaElement) { a.blur(); await new Promise((r) => setTimeout(r, 300)); }  // a line being typed saves on blur
     await settingsRef.current?.flush(); await tl.flush(); await overlays.flush(); };

  const RAIL: { id: string; label: string; icon: React.ReactNode }[] = [
    { id: "lines", label: `Bản dịch${p.segments.length ? ` (${p.segments.length})` : ""}`, icon: <Languages /> },
    { id: "script", label: "Ngôn ngữ & lời thoại", icon: <Sparkles /> },
    { id: "voice", label: "Giọng đọc", icon: <Mic /> },
    { id: "audio", label: "Âm thanh gốc", icon: <AudioLines /> },
    { id: "music", label: "Nhạc nền", icon: <Music /> },
    { id: "subs", label: "Phụ đề", icon: <Captions /> },
    { id: "frame", label: "Khung hình", icon: <Frame /> },
    { id: "color", label: "Chỉnh màu", icon: <Palette /> },
    { id: "logo", label: "Logo", icon: <ImageIcon /> },
    { id: "mask", label: "Che phụ đề gốc", icon: <EyeOff /> },
    { id: "publish", label: "Đăng Reels", icon: <Send /> },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 [&>*]:min-w-0">
      {offline && (
        <div className="flex shrink-0 items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2 text-sm text-destructive">
          <WifiOff className="size-4 shrink-0" />
          Mất kết nối tới server. Kiểm tra server còn chạy không (uv run python -m app). Trang sẽ tự kết nối lại.
        </div>
      )}
      <ActionBar
        project={p}
        previewAt={outAt}
        onStart={() => run(async () => { await flushAll(); return api.start(id, false); })}
        onSaveToFolder={async () => { await run(() => api.saveToFolder(id)); }}
        onRetry={() => run(() => api.retry(id))}
        onCancel={() => run(() => api.cancel(id))}
        onRewrite={async () => { await flushAll(); await run(() => api.rewrite(id)); }}
        onPreview={() => { pendingShow.current = "preview"; run(async () => { await flushAll(); return api.render(id, outAt); }); }}
        onRender={() => { pendingShow.current = "final"; run(async () => { await flushAll(); return api.render(id, null); }); }}
        onJump={(i) => {
          setTab("lines");
          seekAt(p.segments[i].src_id ?? 0, p.segments[i].start + 0.01);
          setTimeout(() => {
            const row = document.querySelector<HTMLElement>(`[data-idx="${i}"]`);
            row?.scrollIntoView({ block: "center", behavior: "smooth" });
            row?.querySelector("textarea")?.focus({ preventScroll: true });
          }, 60);
        }}
      />

      {/* 7 : 3 and as tall as the window. Left: the picture with its player bar, and the timeline. Right: a rail of icons, one panel. */}
      <div className="grid min-h-0 flex-1 gap-2 lg:grid-cols-[minmax(0,7fr)_minmax(340px,3fr)] [&>*]:min-w-0">
        <div className="flex min-h-0 flex-col gap-2 [&>*]:min-w-0">
          <Card className="h-[48vh] min-h-[220px] p-2 sm:p-2 lg:h-auto lg:min-h-0 lg:flex-[3]">
            <VideoPanel
              project={p}
              videoRef={videoRef}
              src={src}
              view={view}
              onView={changeView}
              time={time}
              activeIdx={activeIdx}
              mask={settings.mask}
              color={settings.color}
              overlays={view === "source" ? overlays.items : []}
              outTime={clipPlay.T}
              srcId={loadedSrc}
              edited={tl.edited}
              playing={playing}
              volume={volume}
              muted={muted}
              onVolume={setVolume}
              onMuted={setMuted}
              onTogglePlay={togglePlay}
              scrub={view === "source" && tl.edited ? { value: clipPlay.T, max: totalLen(tl.clips), seek: clipPlay.seekOut } : undefined}
              onSeek={seek}
              onTime={setTime}
              onLoaded={onLoaded}
            />
          </Card>
          <Card className="gap-0 overflow-hidden p-0 lg:min-h-0 lg:flex-[2]">
            <div className="min-h-0 flex-1 overflow-y-auto">
              <TimelinePanel
                project={p}
                tl={tl}
                overlays={overlays}
                editLog={editLog}
                music={settings.music}
                onMusic={(m) => onSettings({ music: m })}
                idx={clipPlay.idx}
                T={clipPlay.T}
                playing={playing}
                showPlayhead={view === "source"}
                disabled={locked}
                onSeekOut={(t) => {
                  if (view === "source") { clipPlay.seekOut(t); return; }
                  // an exported video is showing: go back to the original at that point
                  let acc = 0;
                  let at = { src: 0, t: tl.clips[0]?.start ?? 0 };
                  for (const c of tl.clips) {
                    const l = (c.end - c.start) / (c.speed || 1);
                    at = { src: c.src ?? 0, t: c.start + Math.min(Math.max(t - acc, 0), l) * (c.speed || 1) };
                    if (t < acc + l) break;
                    acc += l;
                  }
                  pendingSeek.current = at.t;
                  setPlaySrc(at.src);
                  setView("source");
                }}
                onSelectClip={clipPlay.setIdx}
                onTogglePlay={togglePlay}
                onApply={apply}
              />
            </div>
          </Card>
        </div>

        <Card className="h-[70vh] min-w-0 flex-row gap-0 overflow-hidden p-0 lg:h-auto lg:min-h-0">
          <nav aria-label="Các mục" className="flex w-11 shrink-0 flex-col items-center gap-1 overflow-y-auto border-r bg-muted/30 py-2">
            {RAIL.map((r) => (
              <IconButton key={r.id} label={r.label} active={tab === r.id} onClick={() => setTab(r.id)}>{r.icon}</IconButton>
            ))}
          </nav>
          <div className="relative min-h-0 min-w-0 flex-1">
            {/* every panel stays mounted (just hidden) so unsaved edits and drafts survive switching */}
            <div className="h-full overflow-y-auto" hidden={tab !== "lines"}>
              <SegmentList
                project={p}
                activeIdx={activeIdx}
                playing={playing}
                onSeek={(t, srcId) => seekAt(srcId, t)}
                onSave={onSave}
                onRegen={onRegen}
                onPlay={onPlay}
              />
            </div>
            <div className="h-full" hidden={!sectionTab}>
              <SettingsPanel
                projectId={id}
                section={sectionTab ?? "script"}
                handle={settingsRef}
                sourceLangs={cfg?.langs ?? {}}
                langLocked={p.segments.length > 0 || (busy && !locked)}
                previewAt={previewAt}
                subStyles={cfg?.sub_styles ?? {}}
                reviewStyles={cfg?.review_styles ?? {}}
                targetLangs={cfg?.target_langs ?? {}}
                translatedTo={p.translated_to ?? "vi"}
                settings={p.settings}
                voices={cfg?.voices ?? {}}
                canDemucs={cfg?.features.demucs ?? false}
                disabled={locked}
                busy={busy}
                onDraft={setDraft}
                onSave={async (patch) => { apply(await api.settings(id, patch)); setDraft(null); }}
                maskDetect={p.mask_detect}
                onDetect={async () => {
                  await run(async () => {
                    const np = await api.detectMask(id);
                    toast.success(np.mask_detect?.found ? "Đã tìm thấy và che vùng phụ đề gốc." : "Không thấy phụ đề gốc trên video.");
                    return np;
                  });
                  setDraft(null);
                }}
              />
            </div>
            <div className="h-full overflow-y-auto" hidden={tab !== "publish"}>
              <PublishPanel project={p} time={previewAt} apply={apply} />
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid gap-5">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(320px,3fr)]">
        <div className="grid gap-5"><Skeleton className="aspect-video" /><Skeleton className="h-56" /></div>
        <div className="grid gap-5"><Skeleton className="h-40" /><Skeleton className="h-[50vh]" /></div>
      </div>
    </div>
  );
}

// settings are locked only while the export runs (it reads them); see app/main.py::patch_settings
const RENDER_STAGES = ["dubbing", "separating", "rendering"];
