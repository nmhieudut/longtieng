"use client";

import type { ReactNode } from "react";

import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

/** One settings page (a tab of the side panel): icon, title and a one-line summary on top, the controls below. */
export function Section({ icon, title, summary, action, children }: {
  value?: string; icon: ReactNode; title: string; summary?: ReactNode; action?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="grid min-w-0 gap-3">
      <header className="flex min-w-0 items-center gap-2 border-b pb-2">
        <span className="text-primary [&_svg]:size-4">{icon}</span>
        <h3 className="shrink-0 text-sm font-semibold">{title}</h3>
        <span className="min-w-0 flex-1 truncate text-right text-xs text-muted-foreground">{summary}</span>
        {action}
      </header>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">{children}</div>
    </section>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

export function SliderField({ label, value, min, max, step, disabled, show, onChange }: {
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
