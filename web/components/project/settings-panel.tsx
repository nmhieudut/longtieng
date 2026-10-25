"use client";

import { Captions, EyeOff, Mic, Music } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { DeepPartial, Settings } from "@/lib/api";

type Props = {
  settings: Settings;
  voices: Record<string, string>;
  disabled: boolean;
  onDraft: (s: Settings) => void;              // live, for the mask overlay
  onSave: (patch: DeepPartial<Settings>) => Promise<void>;
};

export function SettingsPanel({ settings, voices, disabled, onDraft, onSave }: Props) {
  const [s, setS] = useState(settings);
  const pending = useRef<DeepPartial<Settings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // follow the server copy unless a save is queued
  useEffect(() => {
    if (!timer.current) setS(settings);
  }, [settings]);

  function change(patch: DeepPartial<Settings>) {
    const next: Settings = { ...s, ...(patch as Partial<Settings>), mask: { ...s.mask, ...(patch.mask ?? {}) } };
    setS(next);
    onDraft(next);
    pending.current = {
      ...pending.current,
      ...patch,
      ...(patch.mask ? { mask: { ...(pending.current.mask ?? {}), ...patch.mask } } : {}),
    };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const body = pending.current;
      pending.current = {};
      timer.current = null;
      await onSave(body);
    }, 450);
  }

  return (
    <div className="grid gap-6 p-4">
      <Section icon={<Mic />} title="Giọng đọc">
        <Field label="Giọng">
          <Select value={s.voice} disabled={disabled} onValueChange={(v) => change({ voice: v })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.entries(voices).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <SliderField label="Tốc độ nói" value={s.rate} min={0.8} max={1.3} step={0.05} disabled={disabled}
          show={(v) => `${v.toFixed(2)}×`} onChange={(v) => change({ rate: v })} />
      </Section>

      <Separator />

      <Section icon={<Music />} title="Âm thanh gốc">
        <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
          value={s.audio_mode} onValueChange={(v) => v && change({ audio_mode: v as Settings["audio_mode"] })}>
          <ToggleGroupItem value="duck" className="flex-1">Giảm nhỏ</ToggleGroupItem>
          <ToggleGroupItem value="demucs" className="flex-1">Giữ nhạc nền</ToggleGroupItem>
          <ToggleGroupItem value="mute" className="flex-1">Tắt</ToggleGroupItem>
        </ToggleGroup>
        <p className="text-xs text-muted-foreground">
          {s.audio_mode === "duck" && "Giữ âm gốc (cả giọng Trung) ở mức nhỏ, trộn với giọng Việt."}
          {s.audio_mode === "demucs" && "Tách bỏ giọng Trung, chỉ giữ nhạc nền và tiếng động. Chậm hơn vài phút."}
          {s.audio_mode === "mute" && "Chỉ còn giọng lồng tiếng."}
        </p>
        {s.audio_mode !== "mute" && (
          <SliderField label="Âm lượng nền" value={s.orig_volume} min={0} max={1} step={0.05} disabled={disabled}
            show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => change({ orig_volume: v })} />
        )}
      </Section>

      <Separator />

      <Section icon={<Captions />} title="Phụ đề tiếng Việt">
        <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
          value={s.subtitle_mode} onValueChange={(v) => v && change({ subtitle_mode: v as Settings["subtitle_mode"] })}>
          <ToggleGroupItem value="burn" className="flex-1">Ghi vào video</ToggleGroupItem>
          <ToggleGroupItem value="srt" className="flex-1">Chỉ file .srt</ToggleGroupItem>
          <ToggleGroupItem value="none" className="flex-1">Không</ToggleGroupItem>
        </ToggleGroup>
        {s.subtitle_mode === "burn" && (
          <>
            <SliderField label="Cỡ chữ" value={s.sub_size} min={0.5} max={2} step={0.1} disabled={disabled}
              show={(v) => `${v.toFixed(1)}×`} onChange={(v) => change({ sub_size: v })} />
            {!s.mask.enabled && (
              <SliderField label="Cách mép dưới" value={s.sub_margin} min={0} max={50} step={1} disabled={disabled}
                show={(v) => `${v}%`} onChange={(v) => change({ sub_margin: v })} />
            )}
          </>
        )}
      </Section>

      <Separator />

      <Section
        icon={<EyeOff />}
        title="Che phụ đề Trung có sẵn"
        action={<Switch checked={s.mask.enabled} disabled={disabled} onCheckedChange={(v) => change({ mask: { enabled: v } })} />}
      >
        {s.mask.enabled ? (
          <>
            <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
              value={s.mask.style} onValueChange={(v) => v && change({ mask: { style: v as "blur" | "box" } })}>
              <ToggleGroupItem value="blur" className="flex-1">Làm mờ</ToggleGroupItem>
              <ToggleGroupItem value="box" className="flex-1">Dải đen</ToggleGroupItem>
            </ToggleGroup>
            <SliderField label="Cách mép dưới" value={s.mask.bottom} min={0} max={90} step={1} disabled={disabled}
              show={(v) => `${v}%`} onChange={(v) => change({ mask: { bottom: v } })} />
            <SliderField label="Chiều cao" value={s.mask.height} min={2} max={50} step={1} disabled={disabled}
              show={(v) => `${v}%`} onChange={(v) => change({ mask: { height: v } })} />
            <p className="text-xs text-muted-foreground">
              Khung xanh trên video gốc là vùng sẽ bị che. Phụ đề Việt nằm giữa vùng này.
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">Bật nếu video đã có chữ Trung ở đáy màn hình.</p>
        )}
      </Section>
    </div>
  );
}

function Section({ icon, title, action, children }: { icon: ReactNode; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-3">
      <div className="flex items-center gap-2">
        <span className="text-primary [&_svg]:size-4">{icon}</span>
        <h3 className="text-sm font-semibold">{title}</h3>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function SliderField({ label, value, min, max, step, disabled, show, onChange }: {
  label: string; value: number; min: number; max: number; step: number; disabled: boolean;
  show: (v: number) => string; onChange: (v: number) => void;
}) {
  return (
    <div className="grid gap-2.5">
      <div className="flex items-center justify-between">
        <Label className="text-xs text-muted-foreground">{label}</Label>
        <span className="font-mono text-xs tabular-nums">{show(value)}</span>
      </div>
      <Slider value={[value]} min={min} max={max} step={step} disabled={disabled}
        onValueChange={([v]) => onChange(Math.round(v * 100) / 100)} />
    </div>
  );
}
