"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Overlay, type Project } from "@/lib/api";

import { type EditLog, logStep, registerClear } from "./edit-log";

const SAVE_AFTER_MS = 500;
const MAX_HISTORY = 100;

type Hist = { items: Overlay[]; past: Overlay[][]; future: Overlay[][] };

/** Texts and picture stickers of one project: local while you work (with undo), saved to the server a moment later. */
export function useOverlays(project: Project, apply: (p: Project) => void, onError: (m: string) => void, log: EditLog) {
  const server = project.overlays ?? [];
  const serverKey = JSON.stringify(server);
  const [initial] = useState<Hist>(() => ({ items: server, past: [], future: [] }));
  const box = useRef<Hist>(initial);
  const [h, setH] = useState<Hist>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef(0);
  const set = useCallback((next: Hist) => { box.current = next; setH(next); }, []);

  // follow the server copy, unless a save is waiting or on its way
  useEffect(() => {
    if (timer.current || inflight.current) return;
    if (JSON.stringify(box.current.items) !== serverKey) {
      set({ items: JSON.parse(serverKey) as Overlay[], past: box.current.past, future: [] });
    }
  }, [serverKey, set]);

  const save = useCallback(async () => {
    timer.current = null;
    inflight.current++;
    try {
      apply(await api.saveOverlays(project.id, box.current.items));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      inflight.current--;
    }
  }, [apply, onError, project.id]);

  const schedule = useCallback((now = false) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(save, now ? 0 : SAVE_AFTER_MS);
  }, [save]);

  /** Make a change. Changes with the same `key` in quick succession (typing, a slider, a drag) are one undo step. */
  const last = useRef({ key: "", at: 0 });
  const change = useCallback((next: Overlay[], opts: { now?: boolean; key?: string } = {}) => {
    const b = box.current;
    const t = Date.now();
    if (opts.key && last.current.key === opts.key && t - last.current.at < 1200) {
      set({ ...b, items: next, future: [] });
    } else {
      set({ items: next, past: [...b.past.slice(-MAX_HISTORY), b.items], future: [] });
      logStep(log, "ov");
    }
    last.current = { key: opts.key ?? "", at: t };
    schedule(opts.now);
  }, [schedule, set, log]);

  const undo = useCallback(() => {
    const b = box.current;
    const prev = b.past[b.past.length - 1];
    if (!prev) return;
    set({ items: prev, past: b.past.slice(0, -1), future: [...b.future, b.items] });
    last.current = { key: "", at: 0 };
    schedule();
  }, [schedule, set]);

  const redo = useCallback(() => {
    const b = box.current;
    const next = b.future[b.future.length - 1];
    if (!next) return;
    set({ items: next, past: [...b.past, b.items], future: b.future.slice(0, -1) });
    last.current = { key: "", at: 0 };
    schedule();
  }, [schedule, set]);

  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      await save();
    }
    while (inflight.current) await new Promise((r) => setTimeout(r, 30));
  }, [save]);

  useEffect(() => registerClear(log, "ov", () => set({ ...box.current, future: [] })), [log, set]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return { items: h.items, change, undo, redo, flush, canUndo: h.past.length > 0, canRedo: h.future.length > 0 };
}

export type OverlaysApi = ReturnType<typeof useOverlays>;
