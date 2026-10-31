"use client";

import { cn } from "@/lib/utils";

/** The strip between two panes: drag to resize, double-click to go back to the default size. The parent decides
 *  the limits (it gets the pointer position, clamps it, and keeps the panes from covering each other). */
export function ResizeHandle({ orientation, label, onMove, onReset, className }: {
  orientation: "vertical" | "horizontal";   // vertical = a vertical bar between left and right panes
  label: string;
  onMove: (clientX: number, clientY: number) => void;
  onReset: () => void;
  className?: string;
}) {
  const down = (e: React.PointerEvent) => {
    e.preventDefault();
    const prev = document.body.style.cursor;
    document.body.style.cursor = orientation === "vertical" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    const move = (ev: PointerEvent) => onMove(ev.clientX, ev.clientY);
    const up = () => {
      document.body.style.cursor = prev;
      document.body.style.userSelect = "";
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <div role="separator" aria-orientation={orientation} aria-label={label} title={`${label} (bấm đúp để đặt lại)`}
      onPointerDown={down} onDoubleClick={onReset}
      className={cn("group relative z-10 shrink-0 touch-none",
        orientation === "vertical" ? "w-2 cursor-col-resize" : "h-2 cursor-row-resize", className)}>
      <span className={cn("absolute rounded-full bg-border transition-colors group-hover:bg-primary group-active:bg-primary",
        orientation === "vertical" ? "inset-y-0 left-1/2 w-0.5 -translate-x-1/2" : "inset-x-0 top-1/2 h-0.5 -translate-y-1/2")} />
    </div>
  );
}
