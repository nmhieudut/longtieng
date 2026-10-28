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
  lang: string; // key of Config.langs
  voice: string;
  rate: number;
  audio_mode: "duck" | "demucs" | "mute";
  orig_volume: number;
  subtitle_mode: "burn" | "srt" | "none";
  sub_size: number;
  sub_margin: number;
  music: { track: string | null; volume: number; duck: boolean; start: number };
  mask: { enabled: boolean; auto: boolean; style: "blur" | "box"; bottom: number; height: number };
  frame: { aspect: "original" | "9:16" | "16:9" | "1:1" | "4:5"; fit: "blur" | "crop"; zoom: number };
  logo: { image: string | null; text: string; position: "tl" | "tr" | "bl" | "br"; size: number; opacity: number };
  sub_style: string;
  script: { mode: "translate" | "review"; style: string };
};

export type Logo = { id: string; name: string; file: string };

export type Stage =
  | "queued" | "downloading" | "extracting" | "model" | "transcribing" | "detecting" | "translating"
  | "review" | "dubbing" | "separating" | "rendering" | "done" | "error";

export type Caption = { title: string; description: string; hashtags: string[] };
export type CoverPos = "top" | "middle" | "bottom";

export type MusicTrack = { id: string; name: string; file: string; duration: number };

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
  publish?: {
    caption?: Caption;
    candidates?: { t: number; file: string; at: number }[];
    cover?: { t: number; title: string; position: CoverPos; file: string; at: number };
  };
  mask_detect?: { found: boolean; bottom?: number; height?: number };
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

export type VoiceInfo = { label: string; group: string; gender: string; note: string };

export type Config = {
  voices: Record<string, VoiceInfo>;
  defaults: Settings;
  max_upload_mb: number;
  max_duration_min: number;
  translator: string;
  features: { demucs: boolean };
  langs: Record<string, string>;
  sub_styles: Record<string, string>;
  review_styles: Record<string, string>;
  user_defaults: boolean;
  desktop: boolean;
};

export type AppSettings = {
  openai_key_set: boolean;
  openai_key_hint: string;
  stt_engine: string;
  stt_model_ready: boolean;
  data_dir: string;
  version: string;
};

export type UpdateState = {
  stage: "idle" | "none" | "available" | "downloading" | "installing" | "restarting" | "error";
  progress: number | null;
  error: string | null;
  kind: "patch" | "full" | null;
  latest: { version: string; notes?: string; patch?: { size?: number }; mac?: { size?: number }; windows?: { size?: number } } | null;
  current: string;
  enabled: boolean;
};

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };

export const ACTIVE: ReadonlySet<Stage> = new Set([
  "queued", "downloading", "extracting", "model", "transcribing", "detecting", "translating", "dubbing", "separating", "rendering",
]);
export const isActive = (p: Pick<Project, "status"> & { busy?: boolean }) => !!p.busy || ACTIVE.has(p.status.stage);

export const STAGE_LABEL: Record<Stage, string> = {
  queued: "Đang chờ", downloading: "Đang tải", extracting: "Tách âm", model: "Tải model",
  transcribing: "Nhận dạng", detecting: "Dò phụ đề", translating: "Đang dịch", review: "Chờ duyệt", dubbing: "Lồng tiếng",
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
  appSettings: () => req<AppSettings>("/api/app-settings"),
  saveAppSettings: (patch: { openai_key?: string }) =>
    req<AppSettings>("/api/app-settings", { method: "PUT", body: patch }),
  updateState: (force = false) => req<UpdateState>(`/api/update${force ? "?force=1" : ""}`),
  updateApply: () => req<UpdateState>("/api/update/apply", { method: "POST" }),
  list: () => req<ProjectSummary[]>("/api/projects"),
  get: (id: string) => req<Project>(P(id)),
  remove: (id: string) => req<{ ok: boolean }>(P(id), { method: "DELETE" }),
  fromUrl: (url: string, settings: Partial<Settings>, autoRender = false) =>
    req<Project>("/api/projects/url", { method: "POST", body: { url, settings, auto_render: autoRender } }),
  rewrite: (id: string) => req<Project>(`${P(id)}/rewrite`, { method: "POST" }),
  saveDefaults: (settings: Settings) => req<{ ok: boolean }>("/api/default-settings", { method: "PUT", body: { settings } }),
  resetDefaults: () => req<{ ok: boolean }>("/api/default-settings", { method: "DELETE" }),
  logoList: () => req<Logo[]>("/api/logos"),
  logoDelete: (lid: string) => req<{ ok: boolean }>(`/api/logos/${lid}`, { method: "DELETE" }),
  logoUpload: async (file: File): Promise<Logo> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/logos", { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Lỗi ${r.status}`);
    return d as Logo;
  },
  cancel: (id: string) => req<Project>(`${P(id)}/cancel`, { method: "POST" }),
  retry: (id: string) => req<Project>(`${P(id)}/retry`, { method: "POST" }),
  settings: (id: string, settings: DeepPartial<Settings>) =>
    req<Project>(`${P(id)}/settings`, { method: "PATCH", body: settings }),
  editLine: (id: string, sid: number, vi: string) =>
    req<Project>(`${P(id)}/segments/${sid}`, { method: "PATCH", body: { vi } }),
  lineTts: (id: string, sid: number) => req<Project>(`${P(id)}/segments/${sid}/tts`, { method: "POST" }),
  detectMask: (id: string) => req<Project>(`${P(id)}/detect-mask`, { method: "POST" }),
  caption: (id: string) => req<Project>(`${P(id)}/caption`, { method: "POST" }),
  editCaption: (id: string, c: Caption) => req<Project>(`${P(id)}/caption`, { method: "PATCH", body: c }),
  thumbCandidates: (id: string) => req<Project>(`${P(id)}/thumb-candidates`, { method: "POST" }),
  cover: (id: string, t: number, title: string, position: CoverPos) =>
    req<Project>(`${P(id)}/cover`, { method: "POST", body: { t, title, position } }),
  musicList: () => req<MusicTrack[]>("/api/music"),
  musicDelete: (mid: string) => req<{ ok: boolean }>(`/api/music/${mid}`, { method: "DELETE" }),
  musicUpload: async (file: File): Promise<MusicTrack> => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/music", { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Lỗi ${r.status}`);
    return d as MusicTrack;
  },
  render: (id: string, previewStart: number | null) =>
    req<Project>(`${P(id)}/render`, { method: "POST", body: { preview_start: previewStart } }),
};

/** Native helpers exposed by the desktop app (pywebview); undefined in a normal browser. */
type DesktopApi = {
  save_file: (url: string) => Promise<{ saved?: string; cancelled?: boolean; error?: string }>;
  reveal: (path: string) => Promise<void>;
  copy: (text: string) => Promise<void>;
};
export const desktopApi = (): DesktopApi | undefined =>
  typeof window === "undefined" ? undefined : (window as unknown as { pywebview?: { api?: DesktopApi } }).pywebview?.api;

export const logoUrl = (lid: string) => `/api/logos/${lid}/file`;
export const stillUrl = (id: string, t: number) => `${P(id)}/still?t=${t.toFixed(2)}&n=${Date.now()}`;

export const voiceSampleUrl = (voice: string) => `/api/voices/${encodeURIComponent(voice)}/sample`;

export const musicUrl = (mid: string) => `/api/music/${mid}/file`;

export const fileUrl = (id: string, rel: string, v?: number | string) =>
  `${P(id)}/files/${rel}${v ? `?v=${v}` : ""}`;

// XHR rather than fetch: fetch has no upload progress
export function upload(file: File, settings: Partial<Settings>, onProgress: (x: number) => void,
  autoRender = false): Promise<Project> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("settings", JSON.stringify(settings));
    fd.append("auto_render", autoRender ? "true" : "false");
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

/** Clipboard API needs a secure context (localhost is fine, http://192.168… is not). */
export async function copyText(text: string) {
  const bridge = desktopApi();
  if (bridge) {
    await bridge.copy(text);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {}
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

export const fullCaption = (c: Caption) =>
  [c.title, c.description, c.hashtags.join(" ")].filter((x) => x.trim()).join("\n\n");
