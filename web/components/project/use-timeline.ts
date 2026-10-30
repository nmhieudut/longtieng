"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Project } from "@/lib/api";
import { type Clip, full, isFull } from "@/lib/timeline";

const SAVE_AFTER_MS = 500;
const MAX_HISTORY = 100;

type Hist = { clips: Clip[]; past: Clip[][]; future: Clip[][] };

/** The edit list of one project: local while you work (instant, with undo), saved to the server a moment later. */
export function useTimeline(project: Project, apply: (p: Project) => void, onError: (m: string) => void) {
  const duration = project.media?.duration ?? 0;
  const serverClips: Clip[] = project.timeline?.clips?.length ? project.timeline.clips : full(duration);

  // `box` is what the handlers work on (always current, even between two events in one frame);
  // `h` is the same value, kept in state so the screen redraws
  const [initial] = useState<Hist>(() => ({ clips: serverClips, past: [], future: [] }));
  const box = useRef<Hist>(initial);
  const [h, setH] = useState<Hist>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef(0);
  const dragging = useRef(false);
  const set = useCallback((next: Hist) => { box.current = next; setH(next); }, []);

  // follow the server copy, unless a save is waiting or on its way (it would undo what you just did)
  const serverKey = JSON.stringify(serverClips);
  useEffect(() => {
    if (timer.current || inflight.current || dragging.current) return;
    if (JSON.stringify(box.current.clips) !== serverKey) {
      set({ clips: JSON.parse(serverKey) as Clip[], past: box.current.past, future: [] });
    }
  }, [serverKey, set]);

  const save = useCallback(async () => {
    timer.current = null;
    const clips = box.current.clips;
    inflight.current++;
    try {
      apply(await api.saveTimeline(project.id, isFull(clips, duration) ? null : clips));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      inflight.current--;
    }
  }, [apply, duration, onError, project.id]);

  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(save, SAVE_AFTER_MS);
  }, [save]);

  /** Make a change (it can be undone). */
  const commit = useCallback((next: Clip[]) => {
    const b = box.current;
    set({ clips: next, past: [...b.past.slice(-MAX_HISTORY), b.clips], future: [] });
    schedule();
  }, [schedule, set]);

  /** Change made with a slider: many small steps count as one undo step. */
  const lastTweak = useRef({ key: "", at: 0 });
  const tweak = useCallback((next: Clip[], key: string) => {
    const b = box.current;
    const now = Date.now();
    if (lastTweak.current.key === key && now - lastTweak.current.at < 1200) {
      set({ ...b, clips: next, future: [] });
    } else {
      set({ clips: next, past: [...b.past.slice(-MAX_HISTORY), b.clips], future: [] });
    }
    lastTweak.current = { key, at: now };
    schedule();
  }, [schedule, set]);

  /** A change still being dragged: shown at once, but no undo step and no save until it is done. */
  const preview = useCallback((next: Clip[]) => { dragging.current = true; set({ ...box.current, clips: next }); }, [set]);

  /** End of a drag: `before` is what it was when the drag began. */
  const settle = useCallback((before: Clip[]) => {
    dragging.current = false;
    const b = box.current;
    set({ clips: b.clips, past: [...b.past.slice(-MAX_HISTORY), before], future: [] });
    schedule();
  }, [schedule, set]);

  const undo = useCallback(() => {
    const b = box.current;
    const prev = b.past[b.past.length - 1];
    if (!prev) return;
    set({ clips: prev, past: b.past.slice(0, -1), future: [...b.future, b.clips] });
    schedule();
  }, [schedule, set]);

  const redo = useCallback(() => {
    const b = box.current;
    const next = b.future[b.future.length - 1];
    if (!next) return;
    set({ clips: next, past: [...b.past, b.clips], future: b.future.slice(0, -1) });
    schedule();
  }, [schedule, set]);

  /** Save right now (before an export, which reads what is on the server). */
  const flush = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      await save();
    }
    while (inflight.current) await new Promise((r) => setTimeout(r, 30));
  }, [save]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return {
    clips: h.clips, commit, tweak, preview, settle, undo, redo, flush,
    canUndo: h.past.length > 0, canRedo: h.future.length > 0,
    edited: !isFull(h.clips, duration),
  };
}

export type TimelineApi = ReturnType<typeof useTimeline>;
