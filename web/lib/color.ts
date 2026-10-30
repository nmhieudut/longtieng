import type { Settings } from "./api";

export type Color = Settings["color"];

export const COLOR_ZERO: Color = { brightness: 0, contrast: 0, saturation: 0, temperature: 0, sharpness: 0, vignette: 0 };

/** One-tap looks. They only fill in the sliders, so the export needs no knowledge of them. */
export const COLOR_PRESETS: { id: string; label: string; values: Color }[] = [
  { id: "none", label: "Gốc", values: COLOR_ZERO },
  { id: "vivid", label: "Tươi sáng", values: { brightness: 8, contrast: 12, saturation: 30, temperature: 0, sharpness: 25, vignette: 0 } },
  { id: "cinema", label: "Điện ảnh", values: { brightness: -5, contrast: 25, saturation: -12, temperature: -15, sharpness: 15, vignette: 45 } },
  { id: "warm", label: "Ấm", values: { brightness: 5, contrast: 5, saturation: 10, temperature: 45, sharpness: 0, vignette: 0 } },
  { id: "cool", label: "Lạnh", values: { brightness: 0, contrast: 5, saturation: 5, temperature: -45, sharpness: 0, vignette: 0 } },
  { id: "soft", label: "Nhẹ nhàng", values: { brightness: 10, contrast: -12, saturation: -8, temperature: 8, sharpness: 0, vignette: 0 } },
  { id: "retro", label: "Cổ điển", values: { brightness: 2, contrast: 8, saturation: -25, temperature: 28, sharpness: 0, vignette: 45 } },
  { id: "bw", label: "Đen trắng", values: { brightness: 0, contrast: 18, saturation: -100, temperature: 0, sharpness: 0, vignette: 20 } },
];

export const sameColor = (a: Color, b: Color) => (Object.keys(COLOR_ZERO) as (keyof Color)[]).every((k) => a[k] === b[k]);
export const colorIsDefault = (c: Color) => sameColor(c, COLOR_ZERO);

/** Live preview on the original video while sliders move. Close to the export (brightness / contrast / saturation
 *  use the same formulas as ffmpeg's eq); warmth and vignette are overlays. The "Xem ảnh khung hình xuất ra" still
 *  is the exact result, and sharpness only shows there. */
export function cssFilter(c: Color): string {
  return `brightness(${(1 + (c.brightness / 100) * 0.4).toFixed(3)}) contrast(${(1 + (c.contrast / 100) * 0.7).toFixed(3)}) saturate(${(1 + c.saturation / 100).toFixed(3)})`;
}

export function warmthOverlay(c: Color): { background: string; opacity: number } | null {
  if (!c.temperature) return null;
  return { background: c.temperature > 0 ? "#ff8c1a" : "#2f6bff", opacity: (Math.abs(c.temperature) / 100) * 0.4 };
}

export function vignetteOverlay(c: Color): string | null {
  if (!c.vignette) return null;
  return `radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,${((c.vignette / 100) * 0.75).toFixed(2)}) 100%)`;
}
