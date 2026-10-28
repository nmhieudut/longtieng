"use client";

import { Captions, CheckCircle2, EyeOff, Loader2, Mic, Music, ScanText } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Accordion } from "@/components/ui/accordion";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { VoicePicker } from "@/components/voice-picker";

import { MusicSection } from "./music-section";
import { Field, Section, SliderField } from "./settings-ui";
import type { DeepPartial, Project, Settings, VoiceInfo } from "@/lib/api";

type Props = {
  settings: Settings;
  voices: Record<string, VoiceInfo>;
  canDemucs: boolean;
  disabled: boolean;
  onDraft: (s: Settings) => void;              // live, for the mask overlay
  onSave: (patch: DeepPartial<Settings>) => Promise<void>;
  maskDetect?: Project["mask_detect"];
  onDetect: () => Promise<void>;
};

export function SettingsPanel({ settings, voices, canDemucs, disabled, onDraft, onSave, maskDetect, onDetect }: Props) {
  const [detecting, setDetecting] = useState(false);
  const [s, setS] = useState(settings);
  const pending = useRef<DeepPartial<Settings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // follow the server copy unless a save is queued
  useEffect(() => {
    if (!timer.current) setS(settings);
  }, [settings]);

  function change(patch: DeepPartial<Settings>) {
    const next: Settings = {
      ...s, ...(patch as Partial<Settings>),
      mask: { ...s.mask, ...(patch.mask ?? {}) },
      music: { ...s.music, ...(patch.music ?? {}) },
    };
    setS(next);
    onDraft(next);
    pending.current = {
      ...pending.current,
      ...patch,
      ...(patch.mask ? { mask: { ...(pending.current.mask ?? {}), ...patch.mask } } : {}),
      ...(patch.music ? { music: { ...(pending.current.music ?? {}), ...patch.music } } : {}),
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
    <Accordion type="multiple" className="px-4">
      <Section value="voice" icon={<Mic />} title="Giọng đọc"
        summary={`${voices[s.voice]?.label ?? s.voice} · ${s.rate.toFixed(2)}×`}>
        <Field label="Bấm ▶ để nghe thử">
          <VoicePicker voices={voices} value={s.voice} disabled={disabled} onChange={(v) => change({ voice: v })} className="max-h-80" />
        </Field>
        <SliderField label="Tốc độ nói" value={s.rate} min={0.8} max={1.3} step={0.05} disabled={disabled}
          show={(v) => `${v.toFixed(2)}×`} onChange={(v) => change({ rate: v })} />
      </Section>

      <Section value="audio" icon={<Music />} title="Âm thanh gốc"
        summary={s.audio_mode === "mute" ? "Tắt" : `${s.audio_mode === "duck" ? "Giảm nhỏ" : "Giữ nhạc nền"} · ${Math.round(s.orig_volume * 100)}%`}>
        <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
          value={s.audio_mode} onValueChange={(v) => v && change({ audio_mode: v as Settings["audio_mode"] })}>
          <ToggleGroupItem value="duck" className="flex-1">Giảm nhỏ</ToggleGroupItem>
          {(canDemucs || s.audio_mode === "demucs") && (
            <ToggleGroupItem value="demucs" className="flex-1">Giữ nhạc nền</ToggleGroupItem>
          )}
          <ToggleGroupItem value="mute" className="flex-1">Tắt</ToggleGroupItem>
        </ToggleGroup>
        <p className="text-xs text-muted-foreground">
          {s.audio_mode === "duck" && "Giữ âm gốc (cả giọng nói gốc) ở mức nhỏ, trộn với giọng Việt."}
          {s.audio_mode === "demucs" && "Tách bỏ giọng nói gốc, chỉ giữ nhạc nền và tiếng động. Chậm hơn vài phút."}
          {s.audio_mode === "mute" && "Chỉ còn giọng lồng tiếng."}
        </p>
        {s.audio_mode !== "mute" && (
          <SliderField label="Âm lượng nền" value={s.orig_volume} min={0} max={1} step={0.05} disabled={disabled}
            show={(v) => `${Math.round(v * 100)}%`} onChange={(v) => change({ orig_volume: v })} />
        )}
      </Section>

      <MusicSection music={s.music} disabled={disabled} onChange={(m) => change({ music: m })} />

      <Section value="subs" icon={<Captions />} title="Phụ đề tiếng Việt"
        summary={s.subtitle_mode === "burn" ? `Ghi vào video · ${s.sub_size.toFixed(1)}×` : s.subtitle_mode === "srt" ? "Chỉ file .srt" : "Không"}>
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

      <Section
        value="mask"
        icon={<EyeOff />}
        title="Che phụ đề gốc"
        summary={!s.mask.enabled ? "Tắt" : s.mask.auto ? "Tự động · đang che" : "Chỉnh tay · đang che"}
        action={<Switch checked={s.mask.enabled} disabled={disabled} onCheckedChange={(v) => change({ mask: { enabled: v } })} />}
      >
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-xs">
          {s.mask.auto ? (
            maskDetect?.found ? (
              <span className="flex items-center gap-1.5 text-ok"><CheckCircle2 className="size-3.5" />
                Tự nhận diện: có phụ đề gốc, cách đáy {maskDetect.bottom}%, cao {maskDetect.height}%</span>
            ) : maskDetect ? (
              <span className="text-muted-foreground">Tự nhận diện: không thấy phụ đề gốc trên video.</span>
            ) : (
              <span className="text-muted-foreground">Sẽ tự nhận diện khi xử lý video.</span>
            )
          ) : (
            <span className="text-muted-foreground">Đang chỉnh tay.</span>
          )}
          <Button
            size="xs"
            variant="outline"
            className="ml-auto"
            disabled={disabled || detecting}
            onClick={async () => { setDetecting(true); try { await onDetect(); } finally { setDetecting(false); } }}
          >
            {detecting ? <Loader2 className="animate-spin" /> : <ScanText />}
            {detecting ? "Đang dò…" : "Dò tự động"}
          </Button>
        </div>
        {s.mask.enabled && (
          <>
            <ToggleGroup type="single" variant="outline" className="w-full" disabled={disabled}
              value={s.mask.style} onValueChange={(v) => v && change({ mask: { style: v as "blur" | "box" } })}>
              <ToggleGroupItem value="blur" className="flex-1">Làm mờ</ToggleGroupItem>
              <ToggleGroupItem value="box" className="flex-1">Dải đen</ToggleGroupItem>
            </ToggleGroup>
            <SliderField label="Cách mép dưới (chỉnh tay)" value={s.mask.bottom} min={0} max={90} step={0.5} disabled={disabled}
              show={(v) => `${v}%`} onChange={(v) => change({ mask: { bottom: v } })} />
            <SliderField label="Chiều cao (chỉnh tay)" value={s.mask.height} min={2} max={50} step={0.5} disabled={disabled}
              show={(v) => `${v}%`} onChange={(v) => change({ mask: { height: v } })} />
            <p className="text-xs text-muted-foreground">
              Khung xanh trên video gốc là vùng sẽ bị che. Phụ đề Việt nằm giữa vùng này.
            </p>
          </>
        )}
      </Section>
    </Accordion>
  );
}
