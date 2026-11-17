import type { Settings } from "./api";

/** The same numbers as app/frame.py: where the source picture lands on the output canvas.
 *  Keep the two in step (scratch parity check: python app/frame.py vs this file on the same inputs). */
export const ASPECTS: Record<string, [number, number]> = { "9:16": [9, 16], "16:9": [16, 9], "1:1": [1, 1], "4:5": [4, 5] };

export type Geom = { W: number; H: number; s: number; ox: number; oy: number; sw: number; sh: number; active: boolean; blur: boolean };

// Python's round() is "half to even"; this matches it for the values the export sees
function pyRound(x: number): number {
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}
const even = (x: number) => Math.max(2, pyRound(x / 2) * 2);

export function canvas(w: number, h: number, fr: Pick<Settings["frame"], "aspect">): [number, number] {
  const a = ASPECTS[fr.aspect];
  if (!a) return [w, h];
  const long0 = Math.max(w, h);
  const long = long0 >= 1500 ? 1920 : long0 >= 900 ? 1280 : even(long0);
  return a[0] >= a[1] ? [long, even((long * a[1]) / a[0])] : [even((long * a[0]) / a[1]), long];
}

export function geom(w: number, h: number, fr: Pick<Settings["frame"], "aspect" | "fit" | "zoom"> & Partial<Pick<Settings["frame"], "x" | "y">>): Geom {
  const [W, H] = canvas(w, h, fr);
  const zoom = Number(fr.zoom ?? 1);
  const active = W !== w || H !== h || zoom > 1.001;
  if (!active) return { W: w, H: h, s: 1, ox: 0, oy: 0, sw: w, sh: h, active: false, blur: false };
  const s = (fr.fit === "crop" ? Math.max(W / w, H / h) : Math.min(W / w, H / h)) * zoom;
  const sw = even(w * s), sh = even(h * s);
  // centred, then moved by x / y (-1 .. 1) inside the room there is (Python: // then int(round()))
  const ox = Math.floor((W - sw) / 2) + pyRound((fr.x ?? 0) * Math.abs(W - sw) / 2);
  const oy = Math.floor((H - sh) / 2) + pyRound((fr.y ?? 0) * Math.abs(H - sh) / 2);
  return { W, H, s, ox, oy, sw, sh, active: true, blur: sw < W || sh < H };
}
