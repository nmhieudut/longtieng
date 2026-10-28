"use client";

import { Camera, Check, Copy, Download, ImageIcon, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  api, type Caption, copyText, type CoverPos, fileUrl, fmt, fullCaption, type Project,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Props = {
  project: Project;
  time: number;                 // current position of the player (original timeline)
  apply: (p: Project) => void;
};

export function PublishPanel({ project: p, time, apply }: Props) {
  const ready = p.segments.some((s) => s.vi.trim());
  if (!ready) {
    return <p className="px-6 py-16 text-center text-sm text-muted-foreground">Xong bước dịch thì mới viết caption và làm ảnh bìa được.</p>;
  }
  return (
    <div className="grid gap-6 p-4">
      <CaptionBox project={p} apply={apply} />
      <Separator />
      <CoverBox project={p} time={time} apply={apply} />
    </div>
  );
}

function useCopied() {
  const [key, setKey] = useState<string | null>(null);
  const copy = async (k: string, text: string) => {
    await copyText(text);
    setKey(k);
    toast.success("Đã copy");
    setTimeout(() => setKey((x) => (x === k ? null : x)), 1500);
  };
  return { key, copy };
}

// ---------------------------------------------------------------- caption

function CaptionBox({ project: p, apply }: Omit<Props, "time">) {
  const server = p.publish?.caption;
  const [c, setC] = useState<Caption | null>(server ?? null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { key, copy } = useCopied();

  useEffect(() => { if (!timer.current) setC(server ?? null); }, [server]);

  async function generate() {
    setBusy(true);
    try { apply(await api.caption(p.id)); }
    catch (e) { toast.error((e as Error).message); }
    finally { setBusy(false); }
  }

  function edit(patch: Partial<Caption>) {
    if (!c) return;
    const next = { ...c, ...patch };
    setC(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      timer.current = null;
      try { apply(await api.editCaption(p.id, next)); } catch (e) { toast.error((e as Error).message); }
    }, 700);
  }

  return (
    <section className="grid gap-3">
      <Header icon={<Sparkles />} title="Caption">
        {c && (
          <Button size="xs" variant="ghost" disabled={busy} onClick={generate}>
            {busy ? <Loader2 className="animate-spin" /> : <RefreshCw />} Viết lại
          </Button>
        )}
      </Header>

      {!c ? (
        <Button variant="outline" className="h-auto flex-col gap-1 py-5" disabled={busy} onClick={generate}>
          <span className="flex items-center gap-2 font-medium">
            {busy ? <Loader2 className="animate-spin" /> : <Sparkles />} Viết caption bằng AI
          </span>
          <span className="text-xs font-normal text-muted-foreground">Tiêu đề, mô tả và hashtag dựa trên nội dung video</span>
        </Button>
      ) : (
        <>
          <Field label="Tiêu đề" onCopy={() => copy("title", c.title)} copied={key === "title"}>
            <Input value={c.title} onChange={(e) => edit({ title: e.target.value })} />
          </Field>
          <Field label="Mô tả" onCopy={() => copy("desc", c.description)} copied={key === "desc"}>
            <Textarea value={c.description} rows={3} className="field-sizing-content resize-none"
              onChange={(e) => edit({ description: e.target.value })} />
          </Field>
          <Field label="Hashtag" onCopy={() => copy("tags", c.hashtags.join(" "))} copied={key === "tags"}>
            <Input value={c.hashtags.join(" ")}
              onChange={(e) => edit({ hashtags: e.target.value.split(/\s+/).filter(Boolean) })} />
          </Field>
          <Button size="lg" className="h-10" onClick={() => copy("all", fullCaption(c))}>
            {key === "all" ? <Check /> : <Copy />} Copy tất cả để dán vào Facebook
          </Button>
        </>
      )}
    </section>
  );
}

function Field({ label, onCopy, copied, children }: { label: string; onCopy: () => void; copied: boolean; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-muted-foreground">{label}</Label>
        <Button size="xs" variant="ghost" onClick={onCopy}>{copied ? <Check /> : <Copy />} Copy</Button>
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- cover

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu;

function CoverBox({ project: p, time, apply }: Props) {
  const saved = p.publish?.cover;
  const cands = p.publish?.candidates;
  const [picked, setT] = useState<number | null>(saved?.t ?? null);
  const t = picked ?? cands?.[0]?.t ?? null; // first suggestion is the default pick
  const [title, setTitle] = useState(saved?.title ?? (p.publish?.caption?.title ?? "").replace(EMOJI, "").trim());
  const [pos, setPos] = useState<CoverPos>(saved?.position ?? "top");
  const [loadingCands, setLoadingCands] = useState(false);
  const [rendering, setRendering] = useState(false);
  const asked = useRef(false);

  // suggest frames the first time the tab is opened
  useEffect(() => {
    if (cands || asked.current) return;
    asked.current = true;
    setLoadingCands(true);
    api.thumbCandidates(p.id).then(apply).catch((e) => toast.error(e.message)).finally(() => setLoadingCands(false));
  }, [cands, p.id, apply]);

  // fill the title once the AI caption exists
  const capTitle = p.publish?.caption?.title;
  const touched = useRef(!!saved);
  useEffect(() => {
    if (!touched.current && capTitle) setTitle(capTitle.replace(EMOJI, "").trim());
  }, [capTitle]);

  const renderCover = useCallback(async (tt: number, tl: string, ps: CoverPos) => {
    setRendering(true);
    try { apply(await api.cover(p.id, tt, tl, ps)); }
    catch (e) { toast.error((e as Error).message); }
    finally { setRendering(false); }
  }, [p.id, apply]);

  // live preview: re-render shortly after any change
  useEffect(() => {
    if (t === null) return;
    if (saved && saved.t === t && saved.title === title && saved.position === pos) return;
    const h = setTimeout(() => renderCover(t, title, pos), 500);
    return () => clearTimeout(h);
  }, [t, title, pos, saved, renderCover]);

  const coverUrl = saved ? fileUrl(p.id, saved.file, saved.at) : null;
  const vertical = (p.media?.height ?? 0) > (p.media?.width ?? 1);

  return (
    <section className="grid gap-3">
      <Header icon={<ImageIcon />} title="Ảnh bìa">
        <Button size="xs" variant="ghost" disabled={loadingCands}
          onClick={() => { setLoadingCands(true); api.thumbCandidates(p.id).then(apply).catch((e) => toast.error(e.message)).finally(() => setLoadingCands(false)); }}>
          {loadingCands ? <Loader2 className="animate-spin" /> : <RefreshCw />} Gợi ý lại
        </Button>
      </Header>

      <div className="grid gap-1.5">
        <Label className="text-xs text-muted-foreground">Chọn khung hình</Label>
        <div className={cn("grid gap-2", vertical ? "grid-cols-4 sm:grid-cols-7" : "grid-cols-3 sm:grid-cols-4")}>
          {loadingCands && !cands
            ? Array.from({ length: 6 }, (_, i) => <div key={i} className={cn("animate-pulse rounded-md bg-muted", vertical ? "aspect-[9/16]" : "aspect-video")} />)
            : cands?.map((c) => (
              <button key={c.file + c.at} type="button" onClick={() => { touched.current = true; setT(c.t); }}
                className={cn("relative overflow-hidden rounded-md ring-offset-2 ring-offset-background transition",
                  t === c.t ? "ring-2 ring-primary" : "opacity-80 hover:opacity-100")}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={fileUrl(p.id, c.file, c.at)} alt={`Khung ${fmt(c.t)}`} className="block w-full" />
                <span className="absolute bottom-0.5 left-0.5 rounded bg-black/60 px-1 font-mono text-[10px] text-white">{fmt(c.t)}</span>
              </button>
            ))}
          <button type="button" onClick={() => { touched.current = true; setT(Math.round(time * 100) / 100); }}
            className={cn("flex flex-col items-center justify-center gap-1 rounded-md border border-dashed p-2 text-center text-[11px] text-muted-foreground hover:border-primary hover:text-primary",
              vertical ? "aspect-[9/16]" : "aspect-video")}>
            <Camera className="size-4" />
            Khung đang xem {fmt(time)}
          </button>
        </div>
      </div>

      <div className="grid gap-1.5">
        <Label className="text-xs text-muted-foreground">Chữ trên ảnh</Label>
        <Input value={title} placeholder="Tiêu đề in lên ảnh (để trống nếu không cần)"
          onChange={(e) => { touched.current = true; setTitle(e.target.value); }} />
      </div>
      <ToggleGroup type="single" variant="outline" className="w-full" value={pos}
        onValueChange={(v) => { if (v) { touched.current = true; setPos(v as CoverPos); } }}>
        <ToggleGroupItem value="top" className="flex-1">Trên</ToggleGroupItem>
        <ToggleGroupItem value="middle" className="flex-1">Giữa</ToggleGroupItem>
        <ToggleGroupItem value="bottom" className="flex-1">Dưới</ToggleGroupItem>
      </ToggleGroup>

      {coverUrl && (
        <div className="grid gap-2">
          <div className={cn("relative mx-auto overflow-hidden rounded-lg border bg-black", vertical ? "w-56" : "w-full")}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={coverUrl} alt="Ảnh bìa" className={cn("block w-full transition-opacity", rendering && "opacity-60")} />
            {rendering && <Loader2 className="absolute top-2 right-2 size-4 animate-spin text-white" />}
          </div>
          <Button asChild size="lg" className="h-10">
            <a href={`${fileUrl(p.id, saved!.file)}?download=1&t=${saved!.at}`}><Download /> Tải ảnh bìa JPG</a>
          </Button>
        </div>
      )}
    </section>
  );
}

function Header({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-primary [&_svg]:size-4">{icon}</span>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="ml-auto">{children}</div>
    </div>
  );
}
