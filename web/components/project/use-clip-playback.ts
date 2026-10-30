"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

import { type Clip, layout, len, srcOf, trans } from "@/lib/timeline";

/** Clip for a time in the loaded video: keep the current one while the time is inside it, else the first of this
 *  video that holds it, else (the time is in a cut part) the next clip of this video that starts after it.
 *  A repeated clip has the same time in two places, which is why the current one is remembered. */
function pick(clips: Clip[], t: number, current: number, loaded: number): number {
  const mine = (c: Clip) => srcOf(c) === loaded;
  const cur = clips[current];
  if (cur && mine(cur) && t >= cur.start - 0.08 && t < cur.end) return current;
  const hit = clips.findIndex((c) => mine(c) && t >= c.start - 0.08 && t < c.end);
  if (hit >= 0) return hit;
  const after = clips.findIndex((c) => mine(c) && c.start > t);
  if (after >= 0) return after;
  return cur ? current : Math.max(0, clips.length - 1);
}

/** The video element plays one source file; this makes it play only the kept parts, in the edited order,
 *  and asks for another file when the next clip belongs to another video. */
export function useClipPlayback(opts: {
  videoRef: RefObject<HTMLVideoElement | null>;
  clips: Clip[];
  loaded: number;            // which video file the element has loaded (0 = main)
  active: boolean;           // the original video is shown (the exported ones already are the edited video)
  playing: boolean;
  time: number;              // time in the loaded file, as last reported by the video
  onJump: (t: number) => void;                                                         // same file: seek
  onSwitch: (src: number, t: number, autoplay: boolean) => void;                       // another file: load, then seek
}) {
  const { videoRef, clips, loaded, active, playing, time, onJump, onSwitch } = opts;
  const [idx, setIdx] = useState(0);
  const live = useRef({ clips, idx, loaded });
  const wasActive = useRef(false);
  useEffect(() => { live.current = { clips, idx, loaded }; });

  // follow the video while it is not playing (seek, click, undo ...): derived during render, no effect needed
  const wanted = active ? pick(clips, time, idx, loaded) : idx;
  if (wanted !== idx) setIdx(wanted);

  // playing: step through the clips (timeupdate is too coarse, it would run into cut material)
  useEffect(() => {
    if (!active || !playing) return;
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      const { clips: cs, idx: cur, loaded: ld } = live.current;
      if (v && cs.length && srcOf(cs[Math.min(cur, cs.length - 1)]) === ld) {
        const i = pick(cs, v.currentTime, cur, ld);
        const c = cs[i];
        if (i !== cur) setIdx(i);
        const next = cs[i + 1];
        // with a crossfade the export is already on the next clip this much before this one ends
        const cut = next ? c.end - trans(cs, i + 1) * (c.speed || 1) : c.end;
        if (v.currentTime < c.start - 0.08) {            // inside a cut part: go to the clip that follows
          v.currentTime = c.start;
          onJump(c.start);
        } else if (v.currentTime >= cut - 0.03) {
          if (!next) {
            v.pause();
            v.currentTime = c.end;
            onJump(c.end);
          } else {
            setIdx(i + 1);
            live.current = { clips: cs, idx: i + 1, loaded: ld };
            if (srcOf(next) !== ld) {                       // the next part is in another video file
              v.pause();
              onSwitch(srcOf(next), next.start, true);
            } else if (trans(cs, i + 1) > 0 || Math.abs(next.start - c.end) > 0.05) {  // crossfade or not contiguous: jump
              v.currentTime = next.start;
              onJump(next.start);
            }
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, playing, videoRef, onJump, onSwitch]);

  // the video element plays the clip at its speed and volume; anything else (exports, no edit) plays normally
  const cur = clips[Math.min(idx, Math.max(0, clips.length - 1))];
  const rate = active && cur ? cur.speed || 1 : 1;
  const vol = active && cur ? Math.min(1, cur.volume ?? 1) : 1;  // a player cannot go above 100%
  // (re-applied on every time update: a newly loaded file starts again at normal speed and volume)
  useEffect(() => {
    const v = videoRef.current;
    if (v && active) { v.playbackRate = rate; v.volume = vol; }
  }, [videoRef, active, rate, vol, playing, time, loaded]);
  useEffect(() => {  // once, when the timeline lets go of the player; never touches a video nobody edited
    if (active) return;
    const v = videoRef.current;
    if (v && (v.playbackRate !== 1 || v.volume !== 1) && wasActive.current) { v.playbackRate = 1; v.volume = 1; }
    wasActive.current = false;
  }, [videoRef, active]);
  useEffect(() => { if (active) wasActive.current = true; }, [active]);

  const i = Math.min(idx, Math.max(0, clips.length - 1));
  const row = layout(clips)[i];
  const inLoaded = !!row && srcOf(row.clip) === loaded;
  const T = row
    ? row.at + (inLoaded ? Math.min(Math.max(time - row.clip.start, 0), row.clip.end - row.clip.start) / (row.clip.speed || 1) : 0)
    : 0;

  /** Go to output time T: pick its clip, load its video if needed, seek there. */
  const seekOut = useCallback((out: number) => {
    const { clips: cs, loaded: ld } = live.current;
    const rs = layout(cs);
    let k = rs.findIndex((r) => out < r.at + len(r.clip));
    if (k < 0) k = rs.length - 1;
    setIdx(k);
    const src = rs[k].clip.start + Math.min(Math.max(out - rs[k].at, 0), len(rs[k].clip)) * (rs[k].clip.speed || 1);
    if (srcOf(rs[k].clip) !== ld) onSwitch(srcOf(rs[k].clip), src, false);
    else onJump(src);
  }, [onJump, onSwitch]);

  return { idx: i, T, seekOut, setIdx };
}
