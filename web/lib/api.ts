export type FitStatus = "ok" | "fast" | "overflow";
export type Fit = { status: FitStatus; need: number; speed: number; estimated?: boolean } | null;

export type Segment = {
  id: number;
  start: number;
  end: number;
  src: string;
  vi: string;
  tts: { file: string; ver: number; secs: number; text: string; voice: string; rate: number } | null;
  fit: Fit;
};

export type Settings = {
  lang: "zh" | "auto";
  voice: string;
  rate: number;
  audio_mode: "duck" | "demucs" | "mute";
  orig_volume: number;
  subtitle_mode: "burn" | "srt" | "none";
  sub_size: number;
  sub_margin: number;
  mask: { enabled: boolean; style: "blur" | "box"; bottom: number; height: number };
};

export type Stage =
  | "queued" | "downloading" | "extracting" | "model" | "transcribing" | "translating"
  | "review" | "dubbing" | "separating" | "rendering" | "done" | "error";

export type Output = { file: string; at?: number };

export type Project = {
  id: string;
  title: string;
  created: number;
  source: { type: "upload" | "url"; file: string | null; url?: string; name?: string };
  media: { duration: number; width: number; height: number } | null;
  settings: Settings;
  status: { stage: Stage; progress: number | null; message: string; error: string | null };
  warnings: string[];
  segments: Segment[];
  outputs: Partial<Record<"preview" | "final" | "srt" | "json" | "txt", Output>>;
  busy: boolean;
};

export type ProjectSummary = {
  id: string;
  title: string;
  created: number;
  status: Project["status"];
  duration: number | null;
  segments: number;
  has_final: boolean;
};

export type Config = {
  voices: Record<string, string>;
  defaults: Settings;
  max_upload_mb: number;
  max_duration_min: number;
  translator: string;
};

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };

export const ACTIVE: ReadonlySet<Stage> = new Set([
  "queued", "downloading", "extracting", "model", "transcribing", "translating", "dubbing", "separating", "rendering",
]);
export const isActive = (p: Pick<Project, "status"> & { busy?: boolean }) => !!p.busy || ACTIVE.has(p.status.stage);

export const STAGE_LABEL: Record<Stage, string> = {
  queued: "Đang chờ", downloading: "Đang tải", extracting: "Tách âm", model: "Tải model",
  transcribing: "Nhận dạng", translating: "Đang dịch", review: "Chờ duyệt", dubbing: "Lồng tiếng",
  separating: "Tách nhạc", rendering: "Đang xuất", done: "Hoàn tất", error: "Lỗi",
};

async function req<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(path, {
    method: init.method ?? "GET",
    headers: init.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { detail?: string }).detail || `Lỗi ${r.status}`);
  return data as T;
}

const P = (id: string) => `/api/projects/${id}`;

export const api = {
  config: () => req<Config>("/api/config"),
  list: () => req<ProjectSummary[]>("/api/projects"),
  get: (id: string) => req<Project>(P(id)),
  remove: (id: string) => req<{ ok: boolean }>(P(id), { method: "DELETE" }),
  fromUrl: (url: string, settings: Partial<Settings>) =>
    req<Project>("/api/projects/url", { method: "POST", body: { url, settings } }),
  retry: (id: string) => req<Project>(`${P(id)}/retry`, { method: "POST" }),
  settings: (id: string, settings: DeepPartial<Settings>) =>
    req<Project>(`${P(id)}/settings`, { method: "PATCH", body: settings }),
  editLine: (id: string, sid: number, vi: string) =>
    req<Project>(`${P(id)}/segments/${sid}`, { method: "PATCH", body: { vi } }),
  lineTts: (id: string, sid: number) => req<Project>(`${P(id)}/segments/${sid}/tts`, { method: "POST" }),
  render: (id: string, previewStart: number | null) =>
    req<Project>(`${P(id)}/render`, { method: "POST", body: { preview_start: previewStart } }),
};

export const fileUrl = (id: string, rel: string, v?: number | string) =>
  `${P(id)}/files/${rel}${v ? `?v=${v}` : ""}`;

// XHR rather than fetch: fetch has no upload progress
export function upload(file: File, settings: Partial<Settings>, onProgress: (x: number) => void): Promise<Project> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("settings", JSON.stringify(settings));
    const x = new XMLHttpRequest();
    x.open("POST", "/api/projects/upload");
    x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    x.onload = () => {
      let d: { detail?: string } = {};
      try { d = JSON.parse(x.responseText); } catch {}
      if (x.status < 300) resolve(d as Project);
      else reject(new Error(d.detail || `Lỗi ${x.status}`));
    };
    x.onerror = () => reject(new Error("Mất kết nối khi tải lên."));
    x.send(fd);
  });
}

export const fmt = (t: number) => {
  t = Math.max(0, t || 0);
  return `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
};

export function slotOf(p: Project, i: number) {
  const segs = p.segments;
  const next = i + 1 < segs.length ? segs[i + 1].start : p.media?.duration ?? segs[i].end;
  return Math.max(0.3, next - segs[i].start);
}

export function ttsFresh(s: Segment, st: Settings) {
  return !!s.tts && s.tts.text === s.vi.trim() && s.tts.voice === st.voice && Math.abs(s.tts.rate - st.rate) < 1e-3;
}
