"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Overlay, type Project } from "@/lib/api";

const SAVE_AFTER_MS = 500;

/** Texts and picture stickers of one project: local while you work, saved to the server a moment later. */
export function useOverlays(project: Project, apply: (p: Project) => void, onError: (m: string) => void) {
  const server = project.overlays ?? [];
  const serverKey = JSON.stringify(server);
  const [items, setItems] = useState<Overlay[]>(server);
  const latest = useRef(items);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef(0);

  const set = useCallback((next: Overlay[]) => { latest.current = next; setItems(next); }, []);

  // follow the server copy, unless a save is waiting or on its way
  useEffect(() => {
    if (timer.current || inflight.current) return;
    if (JSON.stringify(latest.current) !== serverKey) set(JSON.parse(serverKey) as Overlay[]);
  }, [serverKey, set]);

  const save = useCallback(async () => {
    timer.current = null;
    inflight.current++;
    try {
      apply(await api.saveOverlays(project.id, latest.current));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      inflight.current--;
    }
  }, [apply, onError, project.id]);

  const change = useCallback((next: Overlay[], now = false) => {
    set(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(save, now ? 0 : SAVE_AFTER_MS);
  }, [save, set]);

  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      await save();
    }
    while (inflight.current) await new Promise((r) => setTimeout(r, 30));
  }, [save]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return { items, change, flush };
}

export type OverlaysApi = ReturnType<typeof useOverlays>;
