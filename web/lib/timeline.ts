/** Edit list for the timeline: which parts of which video make the export, in what order, how fast and how loud.
 *  Mirrors app/timeline.py (same rules, so the browser and the export agree on every second). */

export type Clip = {
  id: string;
  start: number;       // seconds in its source video
  end: number;
  src?: number;        // which video: 0 / missing = the project's main video, otherwise an added one
  speed?: number;      // 0.25 .. 4
  volume?: number;     // 0 .. 2, the video's own sound
  fade_in?: number;    // seconds, from/to black and silence
  fade_out?: number;
};

export const MIN_CLIP = 0.2;
export const MIN_SPEED = 0.25;
export const MAX_SPEED = 4;
export const uid = () => Math.random().toString(36).slice(2, 8);

export const spd = (c: Clip) => c.speed || 1;
export const srcOf = (c: Clip) => c.src ?? 0;
/** Seconds the clip lasts in the export. */
export const len = (c: Clip) => (c.end - c.start) / spd(c);
export const totalLen = (clips: Clip[]) => clips.reduce((t, c) => t + len(c), 0);
export const full = (duration: number): Clip[] => [{ id: "full", start: 0, end: duration }];

/** Just a part of the main video: nothing changed about how it plays. */
export const isPlain = (c: Clip) =>
  srcOf(c) === 0 && spd(c) === 1 && (c.volume ?? 1) === 1 && !(c.fade_in || 0) && !(c.fade_out || 0);
export const isFull = (clips: Clip[], duration: number) =>
  clips.length === 1 && clips[0].start <= 0.05 && clips[0].end >= duration - 0.05 && isPlain(clips[0]);

/** Each clip with the output time at which it starts. */
export function layout(clips: Clip[]): { clip: Clip; at: number }[] {
  let t = 0;
  return clips.map((clip) => {
    const row = { clip, at: t };
    t += len(clip);
    return row;
  });
}

/** Which clip plays at output time T, and which second of its video that is. */
export function locate(clips: Clip[], T: number): { idx: number; src: number } {
  const rows = layout(clips);
  for (let i = 0; i < rows.length; i++) {
    const { clip, at } = rows[i];
    if (T < at + len(clip) || i === rows.length - 1) {
      const within = Math.min(Math.max(T - at, 0), len(clip));
      return { idx: i, src: clip.start + within * spd(clip) };
    }
  }
  return { idx: 0, src: 0 };
}

/** Output time of second `src` of the clip's video, inside clip `idx`. */
export function toOut(clips: Clip[], idx: number, src: number): number {
  const row = layout(clips)[idx];
  if (!row) return 0;
  const within = Math.min(Math.max(src - row.clip.start, 0), row.clip.end - row.clip.start);
  return row.at + within / spd(row.clip);
}

/** Cut the clip under output time T in two. null when T is too close to a clip edge. */
export function splitAt(clips: Clip[], T: number): { clips: Clip[]; idx: number } | null {
  const { idx, src } = locate(clips, T);
  const c = clips[idx];
  if (src - c.start < MIN_CLIP || c.end - src < MIN_CLIP) return null;
  const next = [...clips];
  // speed and volume stay on both halves; the fade in belongs to the first, the fade out to the second
  next.splice(idx, 1,
    { ...c, id: uid(), end: src, fade_out: 0 },
    { ...c, id: uid(), start: src, fade_in: 0 });
  return { clips: next, idx: idx + 1 };
}

export const removeAt = (clips: Clip[], idx: number): Clip[] => clips.filter((_, i) => i !== idx);

export function duplicateAt(clips: Clip[], idx: number): Clip[] {
  const next = [...clips];
  next.splice(idx + 1, 0, { ...clips[idx], id: uid() });
  return next;
}

export function moveClip(clips: Clip[], from: number, to: number): Clip[] {
  const next = [...clips];
  const [c] = next.splice(from, 1);
  next.splice(to, 0, c);
  return next;
}

/** Move one edge of a clip to source second `src` (kept inside its video and at least MIN_CLIP long). */
export function trimEdge(clips: Clip[], idx: number, side: "start" | "end", src: number, duration: number): Clip[] {
  const c = clips[idx];
  const next = [...clips];
  next[idx] = side === "start"
    ? { ...c, start: Math.min(Math.max(0, src), c.end - MIN_CLIP) }
    : { ...c, end: Math.max(Math.min(duration, src), c.start + MIN_CLIP) };
  return next;
}

/** Change how a clip plays (speed, volume, fades), keeping every fade inside half the clip. */
export function setProps(clips: Clip[], idx: number, patch: Partial<Pick<Clip, "speed" | "volume" | "fade_in" | "fade_out">>): Clip[] {
  const next = [...clips];
  const c = { ...clips[idx], ...patch };
  if (patch.speed !== undefined) c.speed = Math.min(MAX_SPEED, Math.max(MIN_SPEED, patch.speed));
  const half = len(c) / 2;
  c.fade_in = Math.min(c.fade_in || 0, half);
  c.fade_out = Math.min(c.fade_out || 0, half);
  next[idx] = c;
  return next;
}

type Timed = { start: number; end: number; src_id?: number };

/** Lines in output time (a line belongs to the clip holding its middle, from the same video; cut-out lines are dropped). */
export function mapLines<T extends Timed>(clips: Clip[], segs: T[]): (T & { out0: number; out1: number; clipIdx: number })[] {
  const res: (T & { out0: number; out1: number; clipIdx: number })[] = [];
  layout(clips).forEach(({ clip, at }, clipIdx) => {
    const k = spd(clip);
    for (const s of segs) {
      if ((s.src_id ?? 0) !== srcOf(clip)) continue;
      const mid = (s.start + s.end) / 2;
      if (mid < clip.start || mid >= clip.end) continue;
      res.push({
        ...s,
        out0: at + (Math.max(s.start, clip.start) - clip.start) / k,
        out1: at + (Math.min(s.end, clip.end) - clip.start) / k,
        clipIdx,
      });
    }
  });
  return res;
}

export const clock = (t: number) => {
  const s = Math.max(0, Math.round(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
