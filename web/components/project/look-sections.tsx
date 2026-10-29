"use client";

import { Crop, ImagePlus, Loader2, Sparkles, Stamp, Trash2, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type DeepPartial, type Logo, logoUrl, type Settings } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Field, Section, SliderField } from "./settings-ui";

type Change = (patch: DeepPartial<Settings>) => void;

const ASPECTS: { value: Settings["frame"]["aspect"]; label: string; box: string }[] = [
  { value: "original", label: "Gốc", box: "w-5 h-3.5" },
  { value: "9:16", label: "9:16 Dọc", box: "w-3 h-5" },
  { value: "4:5", label: "4:5", box: "w-4 h-5" },
  { value: "1:1", label: "1:1", box: "w-4 h-4" },
  { value: "16:9", label: "16:9 Ngang", box: "w-5 h-3" },
];

/** Output framing: aspect ratio, how to fill it, zoom. */
export function FrameSection({ s, disabled, change, preview }: {
  s: Settings; disabled: boolean; change: Change; preview: React.ReactNode;
}) {
  const fr = s.frame;
  const label = ASPECTS.find((a) => a.value === fr.aspect)?.label ?? fr.aspect;
  return (
    <Section value="frame" icon={<Crop />} title="Khung hình"
      summary={fr.aspect === "original" && fr.zoom <= 1 ? "Giữ nguyên" :
        `${label}${fr.aspect !== "original" ? (fr.fit === "blur" ? " · nền mờ" : " · cắt khung") : ""}${fr.zoom > 1 ? ` · zoom ${Math.round(fr.zoom * 100)}%` : ""}`}>
      <div className="grid grid-cols-5 gap-1.5" role="radiogroup" aria-label="Tỉ lệ khung">
        {ASPECTS.map((a) => (
          <button key={a.value} type="button" role="radio" aria-checked={fr.aspect === a.value} disabled={disabled}
            onClick={() => change({ frame: { aspect: a.value } })}
            className={cn("grid place-items-center gap-1.5 rounded-lg border px-1 py-2 text-[11px] transition-colors hover:bg-muted disabled:opacity-60",
              fr.aspect === a.value && "border-primary bg-primary/10 font-semibold text-primary hover:bg-primary/10")}>
            <span className={cn("rounded-[3px] border-2 border-current", a.box)} />
            {a.label}
          </button>
        ))}
      </div>
      {fr.aspect !== "original" && (
        <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
          value={fr.fit} onValueChange={(v) => v && change({ frame: { fit: v as "blur" | "crop" } })}>
          <ToggleGroupItem value="blur" className="flex-1">Nền mờ (giữ đủ hình)</ToggleGroupItem>
          <ToggleGroupItem value="crop" className="flex-1">Cắt cho đầy khung</ToggleGroupItem>
        </ToggleGroup>
      )}
      <SliderField label="Phóng to" value={fr.zoom} min={1} max={2} step={0.05} disabled={disabled}
        show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => change({ frame: { zoom: v } })} />
      {preview}
    </Section>
  );
}

const STYLE_SWATCH: Record<string, string> = {
  classic: "text-white [text-shadow:_0_0_3px_#000,0_0_3px_#000]",
  yellow: "text-[#FFE600] [text-shadow:_0_0_3px_#000,0_0_3px_#000]",
  box_dark: "bg-black/75 text-white px-1.5",
  box_yellow: "bg-[#FFE600] text-black px-1.5",
};

/** Subtitle look: a few ready-made styles shown as swatches. */
export function SubStylePicker({ value, styles, disabled, onChange }: {
  value: string; styles: Record<string, string>; disabled: boolean; onChange: (v: string) => void;
}) {
  return (
    <Field label="Kiểu chữ">
      <div className="grid grid-cols-2 gap-1.5 p-1">
        {Object.entries(styles).map(([k, label]) => (
          <button key={k} type="button" disabled={disabled} onClick={() => onChange(k)}
            className={cn("grid gap-1 rounded-lg border bg-[linear-gradient(135deg,#5b6b7a,#2f3b46)] p-2 text-left transition-colors disabled:opacity-60",
              value === k ? "ring-2 ring-primary" : "hover:brightness-110")}>
            <span className={cn("justify-self-center rounded text-sm font-bold", STYLE_SWATCH[k])}>Phụ đề mẫu</span>
            <span className="text-[11px] text-white/85">{label}</span>
          </button>
        ))}
      </div>
    </Field>
  );
}

const CORNERS: { v: Settings["logo"]["position"]; label: string }[] = [
  { v: "tl", label: "Trên trái" }, { v: "tr", label: "Trên phải" },
  { v: "bl", label: "Dưới trái" }, { v: "br", label: "Dưới phải" },
];

/** Channel logo (image from a shared library) or channel name, in a corner. */
export function LogoSection({ s, disabled, change }: { s: Settings; disabled: boolean; change: Change }) {
  const lg = s.logo;
  const [items, setItems] = useState<Logo[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { api.logoList().then(setItems).catch((e) => toast.error(e.message)); }, []);

  const current = items?.find((x) => x.id === lg.image);
  const on = !!(lg.image || lg.text);

  async function upload(f: File) {
    setUploading(true);
    try {
      const item = await api.logoUpload(f);
      setItems((xs) => [...(xs ?? []), item]);
      change({ logo: { image: item.id } });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove(item: Logo) {
    try {
      await api.logoDelete(item.id);
      setItems((xs) => (xs ?? []).filter((x) => x.id !== item.id));
      if (lg.image === item.id) change({ logo: { image: null } });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <Section value="logo" icon={<Stamp />} title="Logo kênh"
      summary={current ? `${current.name} · ${CORNERS.find((c) => c.v === lg.position)?.label}` : lg.text ? lg.text : "Không"}>
      <Field label="Logo ảnh (PNG nền trong suốt đẹp nhất)">
        <div className="flex flex-wrap items-center gap-2 p-1">
          <button type="button" disabled={disabled} onClick={() => change({ logo: { image: null } })}
            className={cn("grid size-14 place-items-center rounded-lg border text-[11px] text-muted-foreground",
              !lg.image && "ring-2 ring-primary")}>Không</button>
          {items?.map((x) => (
            <div key={x.id} className="group relative">
              <button type="button" disabled={disabled} onClick={() => change({ logo: { image: x.id } })}
                title={x.name}
                className={cn("grid size-14 place-items-center overflow-hidden rounded-lg border bg-[repeating-conic-gradient(#ddd_0_25%,#fff_0_50%)] bg-[length:12px_12px] p-1",
                  lg.image === x.id && "ring-2 ring-primary")}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={logoUrl(x.id)} alt={x.name} className="max-h-full max-w-full object-contain" />
              </button>
              <button type="button" aria-label={`Xoá ${x.name}`} onClick={() => remove(x)}
                className="absolute -top-1.5 -right-1.5 hidden size-5 place-items-center rounded-full bg-background text-destructive shadow group-hover:grid">
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
          <button type="button" disabled={disabled || uploading} onClick={() => input.current?.click()}
            className="grid size-14 place-items-center rounded-lg border border-dashed text-muted-foreground hover:bg-muted"
            aria-label="Tải logo lên">
            {uploading ? <Loader2 className="size-4 animate-spin" /> : <ImagePlus className="size-4" />}
          </button>
          <input ref={input} type="file" hidden accept="image/png,image/jpeg,image/webp"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </div>
      </Field>
      {!lg.image && (
        <Field label="Hoặc tên kênh (chữ)">
          <Input placeholder="@kenhcuaban" maxLength={40} defaultValue={lg.text} disabled={disabled}
            onChange={(e) => change({ logo: { text: e.target.value } })} />
        </Field>
      )}
      {on && (
        <>
          <Field label="Vị trí">
            <div className="grid w-40 grid-cols-2 gap-1.5 rounded-lg border p-1.5">
              {CORNERS.map((c) => (
                <button key={c.v} type="button" disabled={disabled} onClick={() => change({ logo: { position: c.v } })}
                  className={cn("rounded-md px-2 py-1.5 text-[11px] hover:bg-muted",
                    lg.position === c.v && "bg-primary text-primary-foreground hover:bg-primary")}>{c.label}</button>
              ))}
            </div>
          </Field>
          <SliderField label="Kích thước" value={lg.size} min={0.05} max={0.4} step={0.01} disabled={disabled}
            show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => change({ logo: { size: v } })} />
          <SliderField label="Độ đậm" value={lg.opacity} min={0.2} max={1} step={0.05} disabled={disabled}
            show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => change({ logo: { opacity: v } })} />
        </>
      )}
    </Section>
  );
}

/** Faithful translation or AI narration ("review") in a chosen style, plus "rewrite now". */
export function ScriptSection({ s, styles, targetLangs, translatedTo, disabled, busy: jobBusy, change, onRewrite }: {
  s: Settings; styles: Record<string, string>; targetLangs: Record<string, { label: string; voice: string }>;
  translatedTo: string; disabled: boolean; busy: boolean; change: Change;
  onRewrite: () => Promise<void>;
}) {
  const sc = s.script;
  const [busy, setBusy] = useState(false);
  const stale = translatedTo !== s.target;
  const label = (k: string) => targetLangs[k]?.label ?? k;
  const lower = (k: string) => label(k).replace(/^Tiếng/, "tiếng");  // "Tiếng Việt" -> "tiếng Việt" inside a sentence
  return (
    <Section value="script" icon={<Sparkles />} title="Lời thoại"
      summary={`${label(s.target)} · ${sc.mode === "review" ? `Review AI · ${styles[sc.style] ?? sc.style}` : "Dịch sát nghĩa"}`}>
      <Field label="Lồng tiếng sang">
        <Select value={s.target} disabled={disabled}
          onValueChange={(t) => change({ target: t, voice: targetLangs[t]?.voice ?? s.voice })}>
          <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(targetLangs).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>
      {stale && (
        <p className="rounded-lg border border-fast/40 bg-fast/10 px-3 py-2 text-xs text-fast-foreground">
          Lời thoại hiện là {lower(translatedTo)}. Bấm “Viết lại lời thoại” bên dưới để dịch sang{" "}
          {lower(s.target)}; chưa viết lại thì chưa xuất video được. Giọng đọc đã tự đổi theo ngôn ngữ mới.
        </p>
      )}
      <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
        value={sc.mode} onValueChange={(v) => v && change({ script: { mode: v as "translate" | "review" } })}>
        <ToggleGroupItem value="translate" className="flex-1">Dịch sát nghĩa</ToggleGroupItem>
        <ToggleGroupItem value="review" className="flex-1">Review / kể chuyện (AI)</ToggleGroupItem>
      </ToggleGroup>
      {sc.mode === "review" && (
        <Field label="Phong cách">
          <Select value={sc.style} disabled={disabled} onValueChange={(v) => change({ script: { style: v } })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(styles).map(([k, label]) => <SelectItem key={k} value={k}>{label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      )}
      <p className="text-xs text-muted-foreground">
        {sc.mode === "review"
          ? "AI viết lại thành lời dẫn kể chuyện theo phong cách đã chọn, vừa khít thời lượng từng đoạn. Cần OpenAI API key."
          : "Dịch đúng lời nhân vật nói."}
      </p>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button variant="outline" disabled={jobBusy || busy} className="justify-self-start"
            title={jobBusy ? "Đợi video xử lý xong" : undefined}>
            {busy ? <Loader2 className="animate-spin" /> : <Wand2 />} Viết lại lời thoại theo cài đặt này
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Viết lại toàn bộ lời thoại?</AlertDialogTitle>
            <AlertDialogDescription>Các câu bạn đã sửa tay sẽ bị thay bằng bản mới. Giọng đọc sẽ được tạo lại khi xuất.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Huỷ</AlertDialogCancel>
            <AlertDialogAction onClick={async () => { setBusy(true); try { await onRewrite(); } finally { setBusy(false); } }}>
              Viết lại
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Section>
  );
}
