"use client";

import type { ReactNode } from "react";

import { AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

/** One collapsible settings group: header shows a one-line summary, body opens on click. */
export function Section({ value, icon, title, summary, action, children }: {
  value: string; icon: ReactNode; title: string; summary?: ReactNode; action?: ReactNode; children: ReactNode;
}) {
  return (
    <AccordionItem value={value} className="border-b last:border-b-0">
      <div className="flex items-center gap-2">
        <AccordionTrigger className="min-w-0 flex-1 items-center gap-2 py-3.5 hover:no-underline">
          <span className="text-primary [&_svg]:size-4">{icon}</span>
          <span className="shrink-0 text-sm font-semibold">{title}</span>
          <span className="min-w-0 flex-1 truncate pl-2 text-right text-xs font-normal text-muted-foreground">{summary}</span>
        </AccordionTrigger>
        {action}
      </div>
      <AccordionContent>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 pb-2">{children}</div>
      </AccordionContent>
    </AccordionItem>
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
