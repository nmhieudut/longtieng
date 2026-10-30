"use client";

import { Crop, ImagePlus, Loader2, Palette, RotateCcw, Sparkles, Stamp, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api, type DeepPartial, type Logo, logoUrl, type Settings } from "@/lib/api";
import { COLOR_PRESETS, COLOR_ZERO, colorIsDefault, sameColor } from "@/lib/color";
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
export function ScriptSection({ s, styles, targetLangs, sourceLangs, langLocked, translatedTo, disabled, change }: {
  s: Settings; styles: Record<string, string>; targetLangs: Record<string, { label: string; voice: string }>;
  sourceLangs: Record<string, string>; langLocked: boolean;   // the spoken language only matters until recognition has run
  translatedTo: string; disabled: boolean; change: Change;
}) {
  const sc = s.script;
  const stale = langLocked && translatedTo !== s.target;
  const label = (k: string) => targetLangs[k]?.label ?? k;
  const lower = (k: string) => label(k).replace(/^Tiếng/, "tiếng");  // "Tiếng Việt" -> "tiếng Việt" inside a sentence
  return (
    <Section value="script" icon={<Sparkles />} title="Ngôn ngữ & lời thoại"
      summary={`${sourceLangs[s.lang] ?? s.lang} → ${label(s.target)} · ${sc.mode === "review" ? `Review AI · ${styles[sc.style] ?? sc.style}` : "Dịch sát nghĩa"}`}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Ngôn ngữ trong video">
          <Select value={s.lang} disabled={disabled || langLocked} onValueChange={(v) => change({ lang: v })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(sourceLangs).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Lồng tiếng sang">
          <Select value={s.target} disabled={disabled}
            onValueChange={(t) => change({ target: t, voice: targetLangs[t]?.voice ?? s.voice })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(targetLangs).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
      </div>
      {langLocked && <p className="text-xs text-muted-foreground">Video đã được nhận dạng nên không đổi ngôn ngữ gốc được nữa. Muốn nhận dạng lại, nhập video này lần nữa.</p>}
      {stale && (
        <p className="rounded-lg border border-fast/40 bg-fast/10 px-3 py-2 text-xs text-fast-foreground">
          Lời thoại hiện là {lower(translatedTo)}. Bấm nút đũa phép “Viết lại lời thoại” ở thanh trên để dịch sang{" "}
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
        {" "}Đổi chế độ hoặc ngôn ngữ xong thì bấm nút đũa phép ở thanh trên để viết lại (khi đã có lời thoại).
      </p>
    </Section>
  );
}

/** Picture adjustments (brightness, contrast, ...) with one-tap looks. */
export function ColorSection({ s, disabled, change }: { s: Settings; disabled: boolean; change: Change }) {
  const c = s.color;
  const preset = COLOR_PRESETS.find((p) => sameColor(p.values, c));
  const show = (v: number) => `${v > 0 ? "+" : ""}${v}`;
  const slider = (key: keyof Settings["color"], label: string, min: number) => (
    <SliderField label={label} value={c[key]} min={min} max={100} step={1} disabled={disabled} show={show}
      onChange={(v) => change({ color: { [key]: Math.round(v) } })} />
  );
  return (
    <Section value="color" icon={<Palette />} title="Chỉnh màu"
      summary={colorIsDefault(c) ? "Giữ nguyên" : preset ? preset.label : "Tuỳ chỉnh"}>
      <div className="flex flex-wrap gap-1.5 p-1" role="radiogroup" aria-label="Bộ lọc màu">
        {COLOR_PRESETS.map((p) => (
          <button key={p.id} type="button" role="radio" aria-checked={preset?.id === p.id} disabled={disabled}
            onClick={() => change({ color: { ...p.values } })}
            className={cn("rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              preset?.id === p.id ? "border-primary bg-primary/10 text-primary ring-1 ring-primary/40" : "hover:bg-accent",
              disabled && "cursor-not-allowed opacity-60")}>
            {p.label}
          </button>
        ))}
      </div>
      {slider("brightness", "Độ sáng", -100)}
      {slider("contrast", "Tương phản", -100)}
      {slider("saturation", "Độ đậm màu", -100)}
      {slider("temperature", "Nhiệt độ màu (lạnh ↔ ấm)", -100)}
      {slider("sharpness", "Độ nét", 0)}
      {slider("vignette", "Tối viền", 0)}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Video gốc ở bên trái đổi màu ngay (gần đúng). Bấm “Xem ảnh khung hình xuất ra” để xem đúng như khi xuất.
        </p>
        <Button type="button" variant="outline" size="sm" disabled={disabled || colorIsDefault(c)}
          onClick={() => change({ color: { ...COLOR_ZERO } })}>
          <RotateCcw /> Về gốc
        </Button>
      </div>
    </Section>
  );
}
