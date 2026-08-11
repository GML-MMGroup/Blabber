"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

type Speaker = "HostA" | "HostB";
type Turn = { speaker: Speaker; text: string };
type Episode = { topic: string; turns: Turn[] };
type SubtitleConfig = { font: string; size: number };
type VideoSegment = { start: number; end: number; duration?: number };
type VideoEdit = { start?: number; end?: number; segments?: VideoSegment[]; duration: number; source_duration: number };
type SubtitleFontInfo = {
  id: string;
  name: string;
  family: string;
  face_family?: string | null;
  installed: boolean;
  downloadable: boolean;
  size_mb?: number | null;
  preview_url?: string | null;
};
type FontResponse = {
  fonts: SubtitleFontInfo[];
  default_font: string;
  font?: SubtitleFontInfo;
  error?: string;
};
type Job = {
  id: string;
  status: "queued" | "running" | "complete" | "failed";
  stage: string;
  completed: number;
  total: number;
  audio_url?: string;
  provider_audio_url?: string;
  episode?: Episode;
  clips?: Array<Turn & { index: number; audio_url: string }>;
  source_type?: "file" | "url" | "text";
  file_name?: string;
  video_url?: string;
  edited_video_url?: string;
  video_edit?: VideoEdit;
  error?: string;
  topic?: string;
  prompt?: string;
  created_at?: string;
  updated_at?: string;
  reused?: boolean;
  creative_config?: {
    background?: string;
    characters?: string[];
    placements?: Placement[];
    voices?: string[];
    subtitles?: SubtitleConfig;
  };
};
type Background = {
  id: string;
  name: string;
  image: string;
  foreground?: string;
  thumbnail?: string;
  accent: string;
};
type Character = {
  id: string;
  name: string;
  image: string;
  actionPreview: string;
  actionId: string;
};
type Voice = { id: string; actionId: Character["actionId"]; name: string; note: string; prompt: string; color: string };
type Placement = { x: number; y: number; scale: number };
type EnvField = {
  key: string;
  group: string;
  label: string;
  default: string;
  help?: string;
  kind?: "url" | "service_url" | "number";
  secret?: boolean;
  configured: boolean;
  value: string;
  restart?: boolean;
};
type ConfigResponse = {
  fields: EnvField[];
  services: Record<string, boolean>;
  saved?: boolean;
};

const defaultPrompt = "做一期关于咖啡文化的轻松播客";
const fallbackSubtitleFonts: SubtitleFontInfo[] = [
  { id: "system", name: "本机中文字体", family: '"PingFang SC", "Microsoft YaHei", sans-serif', installed: true, downloadable: false },
  { id: "noto-sans-sc", name: "思源黑体", face_family: "Blabber Noto Sans SC", family: '"Blabber Noto Sans SC", "Noto Sans CJK SC", sans-serif', installed: false, downloadable: true, size_mb: 15.7 },
  { id: "noto-serif-sc", name: "思源宋体", face_family: "Blabber Noto Serif SC", family: '"Blabber Noto Serif SC", "Noto Serif CJK SC", serif', installed: false, downloadable: true, size_mb: 18 },
];

const backgrounds: Background[] = [
  { id: "zoo", name: "动物园直播间", image: "/scene-zoo.png", foreground: "/scene-zoo-foreground.png", accent: "#34a978" },
  { id: "studio", name: "深夜播客间", image: "/scene-studio-clean.png", foreground: "/scene-studio-foreground.png", thumbnail: "/scene-studio.png", accent: "#8b6cff" },
  { id: "library", name: "复古图书馆", image: "/scene-library.png", foreground: "/scene-library-foreground.png", thumbnail: "/scene-library-composite.jpg", accent: "#b87845" },
  { id: "seaside", name: "海滨电台", image: "/scene-seaside.png", foreground: "/scene-seaside-foreground.png", thumbnail: "/scene-seaside-composite.jpg", accent: "#39a8c8" },
  { id: "space", name: "星际直播舱", image: "/scene-space.png", foreground: "/scene-space-foreground.png", thumbnail: "/scene-space-composite.jpg", accent: "#725df1" },
  { id: "ink-tea", name: "水墨茶室", image: "/scene-ink-tea.png", foreground: "/scene-ink-tea-foreground.png", thumbnail: "/scene-ink-tea-composite.jpg", accent: "#7c8b66" },
  { id: "anime-neon", name: "霓虹动漫台", image: "/scene-anime-neon.png", foreground: "/scene-anime-neon-foreground.png", thumbnail: "/scene-anime-neon-composite.jpg", accent: "#ef5dba" },
  { id: "flat-tech", name: "扁平科技台", image: "/scene-flat-tech.png", foreground: "/scene-flat-tech-foreground.png", thumbnail: "/scene-flat-tech-composite.jpg", accent: "#397ce5" },
  { id: "lowpoly", name: "低多边形演播室", image: "/scene-lowpoly.png", foreground: "/scene-lowpoly-foreground.png", thumbnail: "/scene-lowpoly-composite.jpg", accent: "#8f68d6" },
];

const characters: Character[] = [
  { id: "duck", name: "嘎嘎", image: "/funny-podcast-duck.png", actionPreview: "/action-preview-duck.png", actionId: "duck" },
  { id: "dog", name: "阿汪", image: "/funny-podcast-dog.png", actionPreview: "/action-preview-dog.png", actionId: "dog" },
  { id: "cartoon-female", name: "活力女生", image: "/cartoon-female.png", actionPreview: "/action-preview-female.png", actionId: "female" },
  { id: "cartoon-male", name: "阳光男生", image: "/cartoon-male.png", actionPreview: "/action-preview-male.png", actionId: "male" },
  { id: "anime-reference-host-female", name: "动漫女生", image: "/anime-host-female.png", actionPreview: "/action-preview-anime-reference-host-female.png", actionId: "anime-reference-host-female" },
  { id: "anime-reference-host-male", name: "动漫男生", image: "/anime-host-male.png", actionPreview: "/action-preview-anime-reference-host-male.png", actionId: "anime-reference-host-male" },
  { id: "flat-tech-host-female", name: "科技女生", image: "/flat-tech-host-female.png", actionPreview: "/action-preview-flat-tech-host-female.png", actionId: "flat-tech-host-female" },
  { id: "flat-tech-host-male", name: "科技男生", image: "/flat-tech-host-male.png", actionPreview: "/action-preview-flat-tech-host-male.png", actionId: "flat-tech-host-male" },
  { id: "lowpoly-host-female", name: "低多边形女生", image: "/lowpoly-host-female.png", actionPreview: "/action-preview-lowpoly-host-female.png", actionId: "lowpoly-host-female" },
  { id: "lowpoly-host-male", name: "低多边形男生", image: "/lowpoly-host-male.png", actionPreview: "/action-preview-lowpoly-host-male.png", actionId: "lowpoly-host-male" },
];

const defaultPlacements: Placement[] = [
  { x: 15, y: 0, scale: 1.07 },
  { x: 45, y: 0, scale: 1 },
];

const voices: Voice[] = [
  { id: "zh_female_qiaopinv_uranus_bigtts", actionId: "duck", name: "俏皮女声 2.0", note: "豆包 TTS 2.0 · 俏皮灵动", prompt: "青年感拟人卡通角色，普通话标准，声音清脆明亮、机灵俏皮；语气自信活泼，带自然笑意，吐字清楚，节奏轻快。", color: "#ff9254" },
  { id: "zh_male_wennuanahu_uranus_bigtts", actionId: "dog", name: "温暖阿虎 2.0", note: "豆包 TTS 2.0 · 热情温暖", prompt: "青年男性拟人卡通角色，普通话标准，声音阳光温暖、热情有活力；语气友善又略带顽皮，节奏轻快，具有亲和力。", color: "#31b789" },
  { id: "zh_female_linjianvhai_uranus_bigtts", actionId: "female", name: "邻家女孩 2.0", note: "豆包 TTS 2.0 · 亲切自然", prompt: "青年女性主持人，普通话标准，声音清亮亲切、自然大方；语速适中，表达温暖，带轻松自然的笑意。", color: "#ff6f91" },
  { id: "zh_male_linjiananhai_uranus_bigtts", actionId: "male", name: "邻家男孩 2.0", note: "豆包 TTS 2.0 · 阳光松弛", prompt: "青年男性主持人，普通话标准，声音清朗阳光、自然真诚；语速适中，表达轻松，像亲切健谈的年轻主播。", color: "#4f82ff" },
  { id: "zh_female_tianmeitaozi_uranus_bigtts", actionId: "anime-reference-host-female", name: "甜美桃子 2.0", note: "豆包 TTS 2.0 · 甜美灵动", prompt: "青年女性动漫主持人，普通话标准，声音甜美灵动、清澈自然；情绪丰富但不夸张，语气轻盈，表达活泼专业。", color: "#ee66c4" },
  { id: "zh_male_shaonianzixin_uranus_bigtts", actionId: "anime-reference-host-male", name: "少年梓辛 2.0", note: "豆包 TTS 2.0 · 清爽少年", prompt: "青年男性动漫主持人，普通话标准，声音清爽自信、富有少年感；语气自然有朝气，反应敏捷，节奏明快。", color: "#846cff" },
  { id: "zh_female_cancan_uranus_bigtts", actionId: "flat-tech-host-female", name: "知性灿灿 2.0", note: "豆包 TTS 2.0 · 知性清晰", prompt: "青年女性科技主持人，普通话标准，声音知性清晰、干练亲切；专业术语吐字准确，节奏稳定，表达有条理。", color: "#29a9d6" },
  { id: "zh_male_m191_uranus_bigtts", actionId: "flat-tech-host-male", name: "云舟 2.0", note: "豆包 TTS 2.0 · 清晰专业", prompt: "青年男性科技主持人，普通话标准，声音清晰沉稳、专业可信；表达简洁有条理，语速适中，语气自然从容。", color: "#3376d8" },
  { id: "zh_female_sophie_uranus_bigtts", actionId: "lowpoly-host-female", name: "魅力苏菲 2.0", note: "豆包 TTS 2.0 · 成熟从容", prompt: "成熟女性主持人，普通话标准，声音温和从容、富有质感；表达优雅自然，节奏舒缓，适合文化与创意话题。", color: "#bd6bd6" },
  { id: "zh_male_ruyayichen_uranus_bigtts", actionId: "lowpoly-host-male", name: "儒雅逸辰 2.0", note: "豆包 TTS 2.0 · 温润稳重", prompt: "成熟男性主持人，普通话标准，声音温润稳重、富有质感；语气从容友好，吐字清楚，表达理性而有亲和力。", color: "#8261c9" },
];

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.slice(value.indexOf(",") + 1) : value);
    };
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

function formatFileSize(size: number): string {
  return size < 1024 * 1024
    ? `${Math.max(1, Math.round(size / 1024))} KB`
    : `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatVideoTime(value: number): string {
  const safe = Number.isFinite(value) ? Math.max(0, value) : 0;
  const minutes = Math.floor(safe / 60);
  const seconds = Math.floor(safe % 60);
  const tenths = Math.floor((safe % 1) * 10);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function Wave({ color }: { color: string }) {
  return <span className="voice-wave" style={{ color }} aria-hidden="true">▂▅▃▇▄▆▂▅▇▃▆▄</span>;
}

function nextCharacterSelection(current: string[], id: string): string[] {
  if (current.includes(id)) return current.filter((item) => item !== id);
  if (current.length < 2) return [...current, id];
  return [current[0], id];
}

export default function Home() {
  const [prompt, setPrompt] = useState(defaultPrompt);
  const [episode, setEpisode] = useState<Episode>({ topic: "", turns: [] });
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const sourceFileInput = useRef<HTMLInputElement>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [backgroundId, setBackgroundId] = useState("zoo");
  const [selectedCharacters, setSelectedCharacters] = useState<string[]>(["duck", "dog"]);
  const [placements, setPlacements] = useState<Placement[]>(defaultPlacements);
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [clearConfigKeys, setClearConfigKeys] = useState<string[]>([]);
  const [configBusy, setConfigBusy] = useState(false);
  const [configMessage, setConfigMessage] = useState("");
  const [history, setHistory] = useState<Job[]>([]);
  const [scriptDirty, setScriptDirty] = useState(false);
  const [subtitleDirty, setSubtitleDirty] = useState(false);
  const [subtitleFontId, setSubtitleFontId] = useState("system");
  const [subtitleSize, setSubtitleSize] = useState(48);
  const [subtitleFonts, setSubtitleFonts] = useState<SubtitleFontInfo[]>(fallbackSubtitleFonts);
  const [fontBusy, setFontBusy] = useState("");
  const [fontMessage, setFontMessage] = useState("");
  const loadedFontFaces = useRef(new Set<string>());
  const videoRef = useRef<HTMLVideoElement>(null);
  const [videoDuration, setVideoDuration] = useState(0);
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [playhead, setPlayhead] = useState(0);
  const [trimBusy, setTrimBusy] = useState(false);
  const [trimMessage, setTrimMessage] = useState("");
  const [trimError, setTrimError] = useState(false);
  const [trimPlaying, setTrimPlaying] = useState(false);
  const [trimSegments, setTrimSegments] = useState<VideoSegment[]>([]);

  const background = backgrounds.find((item) => item.id === backgroundId) ?? backgrounds[0];
  const selected = selectedCharacters.map((id) => characters.find((item) => item.id === id)).filter(Boolean) as Character[];
  const selectedSubtitleFont = subtitleFonts.find((item) => item.id === subtitleFontId) ?? subtitleFonts[0];
  const subtitleFontReady = Boolean(selectedSubtitleFont?.installed);
  const videoChangesPending = scriptDirty || subtitleDirty;
  const rawSubtitlePreviewText = episode.turns.find((turn) => turn.text.trim())?.text.trim() || prompt.trim() || "欢迎来到 Blabber 动画播客";
  const subtitlePreviewText = rawSubtitlePreviewText.length > 22 ? `${rawSubtitlePreviewText.slice(0, 22)}…` : rawSubtitlePreviewText;
  const busy = Boolean(job && !["complete", "failed"].includes(job.status));
  const audioReady = Boolean(job?.audio_url);
  const videoReady = Boolean(job?.video_url) && !scriptDirty && !subtitleDirty;
  const videoStage = Boolean(job?.stage?.startsWith("video"));
  const audioActive = Boolean(job && !audioReady && !videoStage && !["complete", "failed"].includes(job.status));
  const videoActive = Boolean(job && videoStage && !["complete", "failed"].includes(job.status));
  const videoWaiting = ["video_queued", "video_waiting", "video_prepare"].includes(job?.stage ?? "");
  const audioProgress = audioReady ? 100 : audioActive && job?.total ? Math.round((job.completed / job.total) * 100) : 0;
  const videoProgress = videoReady
    ? 100
    : videoActive && job?.total
      ? Math.max(0, Math.min(99, Math.round((job.completed / job.total) * 100)))
      : 0;
  const videoButtonLabel = !subtitleFontReady
    ? "请先下载字体"
    : videoChangesPending
      ? "更新字幕并生成"
      : videoReady
        ? "视频已生成"
        : videoWaiting
          ? "正在准备"
          : videoActive
            ? `渲染中 ${videoProgress}%`
            : "生成视频";
  const trimDuration = Math.max(0, trimEnd - trimStart);
  const trimReady = videoReady && videoDuration >= 0.5 && trimDuration >= 0.5;
  const queuedSegments = trimSegments.length ? trimSegments : [{ start: trimStart, end: trimEnd }];
  const savedSegments = job?.video_edit?.segments?.length
    ? job.video_edit.segments
    : typeof job?.video_edit?.start === "number" && typeof job.video_edit.end === "number"
      ? [{ start: job.video_edit.start, end: job.video_edit.end }]
      : [];
  const sequenceDuration = trimSegments.reduce((total, segment) => total + segment.end - segment.start, 0);
  const editDirty = !job?.edited_video_url
    || savedSegments.length !== queuedSegments.length
    || savedSegments.some((segment, index) => (
      Math.abs(segment.start - queuedSegments[index].start) > 0.05
      || Math.abs(segment.end - queuedSegments[index].end) > 0.05
    ));

  const characterSet = "cartoon";

  useEffect(() => {
    void loadHistory();
    void loadSubtitleFonts();
  }, []);

  useEffect(() => {
    const saved = job?.video_edit;
    const duration = saved?.source_duration ?? 0;
    setVideoDuration(duration);
    setTrimStart(saved?.start ?? 0);
    setTrimEnd(saved?.end ?? duration);
    setPlayhead(saved?.start ?? 0);
    setTrimMessage(job?.edited_video_url ? "已恢复上次导出的剪辑片段" : "");
    setTrimError(false);
    setTrimPlaying(false);
    setTrimSegments(saved?.segments?.length
      ? saved.segments.map((segment) => ({ start: segment.start, end: segment.end }))
      : []);
  }, [job?.id, job?.video_url]);

  useEffect(() => {
    if (!job?.id || ["complete", "failed"].includes(job.status)) return;
    const stream = new EventSource(`/api/mvp/jobs/${job.id}/events`);
    stream.onmessage = (event) => {
      const next = JSON.parse(event.data) as Job;
      setJob(next);
      if (next.episode?.turns) setEpisode(next.episode);
      if (["complete", "failed"].includes(next.status)) {
        stream.close();
        void loadHistory();
      }
    };
    stream.onerror = () => {
      stream.close();
      setError("任务事件流连接中断，请从历史记录恢复任务");
    };
    return () => stream.close();
  }, [job?.id, job?.status]);

  async function loadHistory() {
    try {
      const response = await fetch("/api/mvp/history");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "历史记录读取失败");
      setHistory(Array.isArray(payload.items) ? payload.items : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "历史记录读取失败");
    }
  }

  async function activateSubtitleFont(font: SubtitleFontInfo) {
    if (!font.installed || !font.preview_url || !font.face_family || loadedFontFaces.current.has(font.id)) return;
    const face = new FontFace(font.face_family, `url("${font.preview_url}")`);
    await face.load();
    document.fonts.add(face);
    loadedFontFaces.current.add(font.id);
  }

  async function loadSubtitleFonts() {
    try {
      const response = await fetch("/api/mvp/fonts");
      const next: FontResponse = await response.json();
      if (!response.ok) throw new Error(next.error || "字体列表读取失败");
      const available = Array.isArray(next.fonts) && next.fonts.length ? next.fonts : fallbackSubtitleFonts;
      setSubtitleFonts(available);
      setSubtitleFontId((current) => available.some((font) => font.id === current && (font.installed || current !== "system")) ? current : next.default_font);
      await Promise.all(available.map((font) => activateSubtitleFont(font)));
    } catch (cause) {
      setFontMessage(cause instanceof Error ? cause.message : "字体列表读取失败");
    }
  }

  async function downloadSubtitleFont(fontId: string) {
    setFontBusy(fontId);
    setFontMessage("");
    try {
      const response = await fetch(`/api/mvp/fonts/${fontId}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const next: FontResponse = await response.json();
      if (!response.ok || !next.font) throw new Error(next.error || "字体下载失败");
      setSubtitleFonts(next.fonts);
      await activateSubtitleFont(next.font);
      setSubtitleFontId(fontId);
      setFontMessage(`${next.font.name}已下载，可用于预览和视频合成`);
    } catch (cause) {
      setFontMessage(cause instanceof Error ? cause.message : "字体下载失败");
    } finally {
      setFontBusy("");
    }
  }

  function restoreHistory(item: Job) {
    setJob(item);
    if (item.episode) setEpisode(item.episode);
    setPrompt(item.topic || item.prompt || item.episode?.topic || "");
    setSourceFile(null);
    if (sourceFileInput.current) sourceFileInput.current.value = "";
    setError("");
    setScriptDirty(false);
    const savedSubtitles = item.creative_config?.subtitles;
    if (savedSubtitles) {
      setSubtitleFontId(savedSubtitles.font);
      setSubtitleSize(savedSubtitles.size);
    }
    setSubtitleDirty(false);
  }

  function updateSubtitleFont(fontId: string) {
    setSubtitleFontId(fontId);
    setFontMessage("");
    if (job?.video_url) setSubtitleDirty(true);
  }

  function updateSubtitleSize(size: number) {
    setSubtitleSize(size);
    if (job?.video_url) setSubtitleDirty(true);
  }

  function updateTurn(index: number, changes: Partial<Turn>) {
    setEpisode((current) => ({ ...current, turns: current.turns.map((turn, turnIndex) => turnIndex === index ? { ...turn, ...changes } : turn) }));
    if (audioReady) setScriptDirty(true);
  }

  function deleteTurn(index: number) {
    setEpisode((current) => ({ ...current, turns: current.turns.filter((_, turnIndex) => turnIndex !== index) }));
  }

  function addTurn() {
    insertTurnAt(episode.turns.length);
  }

  function insertTurnAt(index: number) {
    setEpisode((current) => {
      const previous = current.turns[index - 1]?.speaker;
      const next = current.turns[index]?.speaker;
      const speaker: Speaker = previous
        ? previous === "HostA" ? "HostB" : "HostA"
        : next
          ? next === "HostA" ? "HostB" : "HostA"
          : "HostA";
      const turns = [...current.turns];
      turns.splice(index, 0, { speaker, text: "" });
      return { ...current, turns };
    });
  }

  function chooseCharacter(id: string) {
    setSelectedCharacters((current) => nextCharacterSelection(current, id));
  }

  function updatePlacement(index: number, key: keyof Placement, value: number) {
    setPlacements((current) => current.map((item, placementIndex) => placementIndex === index ? { ...item, [key]: value } : item));
  }

  async function openConfig() {
    setConfigOpen(true);
    setConfigBusy(true);
    setConfigMessage("");
    try {
      const response = await fetch("/api/mvp/config");
      const next: ConfigResponse & { error?: string } = await response.json();
      if (!response.ok) throw new Error(next.error || "配置读取失败");
      setConfig(next);
      setConfigValues(Object.fromEntries(next.fields.map((field) => [field.key, field.value])));
      setClearConfigKeys([]);
    } catch (cause) {
      setConfigMessage(cause instanceof Error ? cause.message : "配置读取失败");
    } finally {
      setConfigBusy(false);
    }
  }

  async function saveConfig() {
    setConfigBusy(true);
    setConfigMessage("");
    try {
      const response = await fetch("/api/mvp/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: configValues, clear: clearConfigKeys }),
      });
      const next: ConfigResponse & { error?: string } = await response.json();
      if (!response.ok) throw new Error(next.error || "配置保存失败");
      setConfig(next);
      setConfigValues(Object.fromEntries(next.fields.map((field) => [field.key, field.value])));
      setClearConfigKeys([]);
      setError("");
      setJob((current) => current?.status === "failed" ? null : current);
      setConfigMessage("服务凭证已保存并应用；之前已开始的任务不受影响。");
    } catch (cause) {
      setConfigMessage(cause instanceof Error ? cause.message : "配置保存失败");
    } finally {
      setConfigBusy(false);
    }
  }

  async function generateAudio() {
    if (!sourceFile && !prompt.trim()) return;
    setError("");
    const chosenVoices = selected.slice(0, 2).map((character) =>
      voices.find((voice) => voice.actionId === character.actionId) ?? voices[0]
    );
    if (chosenVoices.length < 2) {
      setError("请先选择两位角色");
      return;
    }
    try {
      const documentBody = sourceFile ? {
        file_name: sourceFile.name,
        file_base64: await fileToBase64(sourceFile),
        topic: prompt.trim() || sourceFile.name.replace(/\.[^.]+$/, ""),
        creative_config: {
          background: background.id,
          characters: selected.map((item) => item.actionId),
          placements,
          voices: chosenVoices.map((voice) => voice.id),
          subtitles: { font: subtitleFontId, size: subtitleSize },
        },
      } : null;
      const response = await fetch(
        sourceFile ? "/api/mvp/document-jobs" : "/api/mvp/jobs",
        {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(documentBody ?? {
          prompt,
          character_set: characterSet,
          custom_voices: {
            HostA: chosenVoices[0].prompt,
            HostB: chosenVoices[1].prompt,
          },
          creative_config: {
            background: background.id,
            characters: selected.map((item) => item.actionId),
            placements,
            voices: chosenVoices.map((voice) => voice.id),
            subtitles: { font: subtitleFontId, size: subtitleSize },
          },
        }),
      });
      const next = await response.json();
      if (!response.ok) throw new Error(next.error || "播客任务创建失败");
      setEpisode(next.episode ?? { topic: documentBody?.topic || prompt, turns: [] });
      setJob(next);
      setScriptDirty(false);
      const nextSubtitles = next.creative_config?.subtitles as SubtitleConfig | undefined;
      setSubtitleDirty(Boolean(next.video_url) && (
        nextSubtitles?.font !== subtitleFontId || nextSubtitles?.size !== subtitleSize
      ));
      if (next.reused) void loadHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "播客任务创建失败");
    }
  }

  async function generateVideo() {
    if (!job?.id || !job.audio_url || selected.length < 2) return;
    if (!selectedSubtitleFont?.installed) {
      setError(`请先下载字幕字体“${selectedSubtitleFont?.name || subtitleFontId}”`);
      return;
    }
    setError("");
    setTrimMessage("");
    setTrimError(false);
    try {
      const response = await fetch(`/api/mvp/jobs/${job.id}/video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "action",
          episode,
          force: scriptDirty || subtitleDirty,
          creative_config: {
            background: background.id,
            characters: selected.map((item) => item.actionId),
            placements,
            subtitles: { font: subtitleFontId, size: subtitleSize },
          },
        }),
      });
      const next = await response.json();
      if (!response.ok) throw new Error(next.error || "视频任务创建失败");
      setJob(next);
      setScriptDirty(false);
      setSubtitleDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "视频任务创建失败");
    }
  }

  function seekVideo(value: number) {
    const video = videoRef.current;
    const next = Math.max(0, Math.min(value, videoDuration || value));
    if (video) video.currentTime = next;
    setPlayhead(next);
  }

  function loadVideoMetadata(video: HTMLVideoElement) {
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    const saved = job?.video_edit;
    const savedSegment = saved?.segments?.[0]
      ?? (typeof saved?.start === "number" && typeof saved.end === "number"
        ? { start: saved.start, end: saved.end }
        : null);
    const start = savedSegment ? Math.min(savedSegment.start, Math.max(0, duration - 0.5)) : 0;
    const end = savedSegment ? Math.min(savedSegment.end, duration) : duration;
    setVideoDuration(duration);
    setTrimStart(start);
    setTrimEnd(Math.max(start + Math.min(0.5, duration), end));
    setPlayhead(start);
  }

  function updateTrimStart(value: number) {
    const next = Math.max(0, Math.min(value, trimEnd - 0.5));
    setTrimStart(next);
    setTrimMessage("");
    setTrimError(false);
    seekVideo(next);
  }

  function updateTrimEnd(value: number) {
    const next = Math.min(videoDuration, Math.max(value, trimStart + 0.5));
    setTrimEnd(next);
    setTrimMessage("");
    setTrimError(false);
    seekVideo(next);
  }

  function setBoundaryFromPlayhead(boundary: "start" | "end") {
    const current = videoRef.current?.currentTime ?? playhead;
    if (boundary === "start") updateTrimStart(current);
    else updateTrimEnd(current);
  }

  function resetTrim() {
    setTrimStart(0);
    setTrimEnd(videoDuration);
    setTrimMessage("");
    setTrimError(false);
    seekVideo(0);
  }

  function addTrimSegment() {
    if (!trimReady) return;
    if (trimSegments.length >= 20) {
      setTrimError(true);
      setTrimMessage("一次最多拼接 20 个片段");
      return;
    }
    setTrimSegments((current) => [...current, { start: trimStart, end: trimEnd }]);
    setTrimError(false);
    setTrimMessage(`已加入片段 ${formatVideoTime(trimStart)} — ${formatVideoTime(trimEnd)}`);
  }

  function selectTrimSegment(segment: VideoSegment) {
    videoRef.current?.pause();
    setTrimStart(segment.start);
    setTrimEnd(segment.end);
    setTrimError(false);
    setTrimMessage("已在时间轴中选中该片段");
    seekVideo(segment.start);
  }

  function moveTrimSegment(index: number, offset: -1 | 1) {
    setTrimSegments((current) => {
      const target = index + offset;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
    setTrimMessage("");
    setTrimError(false);
  }

  function removeTrimSegment(index: number) {
    setTrimSegments((current) => current.filter((_, itemIndex) => itemIndex !== index));
    setTrimMessage("");
    setTrimError(false);
  }

  function clearTrimSegments() {
    setTrimSegments([]);
    setTrimMessage("拼接序列已清空，将直接导出当前选区");
    setTrimError(false);
  }

  async function previewTrim() {
    const video = videoRef.current;
    if (!video || !trimReady) return;
    if (!video.paused && video.currentTime >= trimStart && video.currentTime < trimEnd) {
      video.pause();
      return;
    }
    if (video.currentTime < trimStart || video.currentTime >= trimEnd - 0.05) {
      video.currentTime = trimStart;
      setPlayhead(trimStart);
    }
    try {
      await video.play();
    } catch {
      setTrimError(true);
      setTrimMessage("浏览器阻止了自动播放，请直接使用视频播放按钮");
    }
  }

  function updateVideoPlayhead(video: HTMLVideoElement) {
    const current = video.currentTime;
    setPlayhead(current);
    if (!video.paused && trimReady && current >= trimEnd) {
      video.pause();
      video.currentTime = trimStart;
      setPlayhead(trimStart);
    }
  }

  async function exportVideoEdit() {
    if (!job?.id || !trimReady || trimBusy) return;
    setTrimBusy(true);
    setTrimError(false);
    setTrimMessage("正在导出剪辑片段，请稍候…");
    try {
      const response = await fetch(`/api/mvp/jobs/${job.id}/video/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          segments: queuedSegments.map((segment) => ({
            start: segment.start,
            end: segment.end,
          })),
        }),
      });
      const next = await response.json() as Job & { error?: string };
      if (!response.ok) throw new Error(next.error || "视频剪辑失败");
      setJob(next);
      setTrimSegments((next.video_edit?.segments ?? queuedSegments).map((segment) => ({
        start: segment.start,
        end: segment.end,
      })));
      setTrimMessage(`${queuedSegments.length > 1 ? "拼接视频" : "剪辑片段"}已导出，共 ${formatVideoTime(next.video_edit?.duration ?? trimDuration)}`);
      void loadHistory();
    } catch (cause) {
      setTrimError(true);
      setTrimMessage(cause instanceof Error ? cause.message : "视频剪辑失败");
    } finally {
      setTrimBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="studio-layout" id="top">
        <aside className="script-column">
          <div className="prompt-card">
            <div className="prompt-label"><span>✦</span>{sourceFile ? " 为文档补充节目标题（可选）" : " 描述你想制作的节目"}</div>
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={3} aria-label="播客主题" />
            <div className="generation-actions">
              <label>
                <input
                  ref={sourceFileInput}
                  type="file"
                  accept=".txt,.md,.markdown,.html,.htm,.json,.csv,.docx,.pdf"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    if (file && file.size > 20 * 1024 * 1024) {
                      setError("上传文件不能超过 20MB");
                      event.target.value = "";
                      return;
                    }
                    setError("");
                    setSourceFile(file);
                    if (file) setPrompt("");
                  }}
                />
                <span>＋ 传入文件</span>
              </label>
              <button className="generate-audio" onClick={generateAudio} disabled={busy || selected.length < 2 || (!sourceFile && !prompt.trim())}>{audioActive ? "生成中…" : "生成脚本和音频"}<span>↗</span></button>
            </div>
            {sourceFile && <div className="selected-document"><b>{sourceFile.name}</b><small>{formatFileSize(sourceFile.size)}</small><button onClick={() => {
                setSourceFile(null);
                if (sourceFileInput.current) sourceFileInput.current.value = "";
              }} aria-label="移除文件">×</button></div>}
          </div>

          <section className="history-panel" aria-label="生成历史记录">
            <header><b>历史记录</b><button onClick={() => void loadHistory()}>刷新</button></header>
            <div>
              {history.filter((item) => item.audio_url).slice(0, 20).map((item) => <button className={job?.id === item.id ? "active" : ""} onClick={() => restoreHistory(item)} key={item.id}>
                <span><b>{item.episode?.topic || item.topic || item.prompt || item.file_name || "未命名播客"}</b><small>{item.file_name || `${item.episode?.turns?.length ?? item.clips?.length ?? 0} 个切片`}</small></span>
                <time>{item.updated_at ? new Date(item.updated_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}</time>
              </button>)}
              {!history.some((item) => item.audio_url) && <p>完成一次生成后，可在这里直接恢复，避免重复请求。</p>}
            </div>
          </section>

          <div className="script-editor-head">
            <label>{audioActive ? "正在接收脚本切片…" : episode.turns.length ? "脚本和音频已生成" : "生成后显示脚本切片"}</label>
            <span>{episode.turns.length} 句</span>
          </div>
          <div className="turn-editor">
            <button className="insert-turn first" onClick={() => insertTurnAt(0)} disabled={audioReady}>＋ 在开头插入对白</button>
            {episode.turns.map((turn, index) => (
              <Fragment key={`${index}-${turn.speaker}`}>
                <article className={`edit-turn ${turn.speaker === "HostB" ? "host-b" : ""}`}>
                  <button className="speaker-toggle" disabled={audioReady} onClick={() => updateTurn(index, { speaker: turn.speaker === "HostA" ? "HostB" : "HostA" })}>{turn.speaker === "HostA" ? "A" : "B"}</button>
                  <textarea value={turn.text} placeholder="输入新的对白…" onChange={(event) => updateTurn(index, { text: event.target.value })} rows={Math.max(2, Math.ceil(turn.text.length / 23))} aria-label={`第 ${index + 1} 句对白`} />
                  <button className="delete-turn" disabled={audioReady} onClick={() => deleteTurn(index)} aria-label={`删除第 ${index + 1} 句`}>×</button>
                </article>
                {index < episode.turns.length - 1 && <button className="insert-turn" disabled={audioReady} onClick={() => insertTurnAt(index + 1)}>＋ 在此处插入</button>}
              </Fragment>
            ))}
          </div>
          <button className="add-turn" onClick={addTurn} disabled={audioReady}>＋ 在末尾添加对白</button>
        </aside>

        <section className="preview-column">
          <div className="canvas-wrap">
            <div className="preview-canvas" style={{ "--scene-accent": background.accent } as CSSProperties}>
              {videoReady ? (
                <video
                  ref={videoRef}
                  controls
                  autoPlay={false}
                  src={job?.video_url}
                  onLoadedMetadata={(event) => loadVideoMetadata(event.currentTarget)}
                  onTimeUpdate={(event) => updateVideoPlayhead(event.currentTarget)}
                  onPlay={() => setTrimPlaying(true)}
                  onPause={() => setTrimPlaying(false)}
                >浏览器不支持视频播放。</video>
              ) : (
                <>
                  <img className="scene-background" src={background.image} alt={background.name} />
                  {selected.slice(0, 2).map((character, index) => {
                    const placement = placements[index] ?? defaultPlacements[index];
                    const actionSize = 700 * placement.scale;
                    return <img
                      key={character.id}
                      className={`canvas-character character-${index}`}
                      src={character.actionPreview}
                      alt={`${character.name}，${index === 0 ? "左侧" : "右侧"}`}
                      style={{
                        left: `${placement.x}%`,
                        top: `${((245 - placement.y * 8) / 1080) * 100}%`,
                        width: `${(actionSize / 1920) * 100}%`,
                      } as CSSProperties}
                    />;
                  })}
                  {background.foreground && <img className="scene-foreground" src={background.foreground} alt="场景前景" />}
                  <div className="on-air-pill"><i /> ON AIR</div>
                  <div
                    className={`subtitle-preview ${subtitleFontReady ? "" : "font-missing"}`}
                    title={subtitleFontReady ? "字幕预览" : "下载字体后显示准确预览"}
                    style={{
                      fontFamily: selectedSubtitleFont?.family,
                      fontSize: `clamp(10px, ${(subtitleSize / 19.2).toFixed(3)}cqw, 34px)`,
                    }}
                  ><span>{subtitlePreviewText}</span></div>
                </>
              )}
            </div>
          </div>

          <div className="production-steps" aria-label="节目生成进度">
            <article className={`status-only ${audioReady ? "done" : audioActive ? "active" : ""}`}>
              <span className="production-index">1</span>
              <div className="production-copy"><b>播客生成状态</b><small>{audioReady ? `已返回 ${job?.clips?.length ?? episode.turns.length} 个文本/音频切片` : audioActive ? `PodcastTTS 生成中 · ${audioProgress}%` : "等待从左栏开始生成"}</small><progress value={audioProgress} max={100} /></div>
            </article>
            <article className={videoReady ? "done" : videoActive ? "active" : !audioReady ? "locked" : ""}>
              <span className="production-index">2</span>
              <div className="production-copy"><b>生成视频</b><small>{subtitleDirty ? "字幕字体或字号已修改，将重新合成" : scriptDirty ? "脚本已修改，将同步更新字幕" : videoReady ? "成片已就绪" : videoWaiting ? "正在等待渲染资源" : videoActive ? `正在合成 · ${videoProgress}%` : audioReady ? "将语音、角色动作、字幕与场景合成" : "请先完成语音合成"}</small><progress value={videoProgress} max={100} /></div>
              <button
                className={`video-generate-button ${videoWaiting || videoActive ? "is-rendering" : videoReady ? "is-complete" : ""}`}
                onClick={generateVideo}
                disabled={busy || videoReady || !audioReady || selected.length < 2 || !subtitleFontReady}
                aria-live="polite"
              >
                <span className="video-button-orbit" aria-hidden="true"><i /></span>
                <span className="video-button-label">{videoButtonLabel}</span>
                <span className="video-button-sheen" aria-hidden="true" />
              </button>
            </article>
          </div>

          <section className={`video-editor ${videoReady ? "" : "locked"}`} aria-label="视频裁剪与拼接">
            <header>
              <span><b>视频裁剪与拼接</b><small>{videoReady ? "选择范围加入序列，再按顺序拼接导出" : "生成视频后可裁剪、排序并拼接片段"}</small></span>
              <output>{formatVideoTime(trimStart)} — {formatVideoTime(trimEnd)}</output>
            </header>
            <div className="trim-toolbar">
              <button onClick={() => void previewTrim()} disabled={!trimReady}>{trimPlaying ? "Ⅱ 暂停" : "▶ 预览选区"}</button>
              <button onClick={() => setBoundaryFromPlayhead("start")} disabled={!trimReady}>设当前为入点</button>
              <button onClick={() => setBoundaryFromPlayhead("end")} disabled={!trimReady}>设当前为出点</button>
              <button onClick={resetTrim} disabled={!trimReady}>重置</button>
              <button className="add-segment" onClick={addTrimSegment} disabled={!trimReady || trimSegments.length >= 20}>＋ 加入拼接序列</button>
            </div>
            <div
              className="trim-timeline"
              style={{
                "--trim-start": `${videoDuration ? (trimStart / videoDuration) * 100 : 0}%`,
                "--trim-end": `${videoDuration ? (trimEnd / videoDuration) * 100 : 100}%`,
                "--playhead": `${videoDuration ? (playhead / videoDuration) * 100 : 0}%`,
              } as CSSProperties}
            >
              <div className="trim-thumbnails" aria-hidden="true">
                {[0, 1, 2, 3, 4, 5].map((item) => <span key={item}><img src={background.thumbnail ?? background.image} alt="" /></span>)}
              </div>
              <div className="trim-shade before" aria-hidden="true" />
              <div className="trim-shade after" aria-hidden="true" />
              <div className="trim-selection" aria-hidden="true" />
              <i className="trim-playhead" aria-hidden="true" />
              <label className="trim-handle start">
                <span>入点</span>
                <input type="range" min="0" max={videoDuration || 0} step="0.1" value={trimStart} onChange={(event) => updateTrimStart(Number(event.target.value))} disabled={!videoReady || !videoDuration} aria-label="剪辑入点" />
              </label>
              <label className="trim-handle end">
                <span>出点</span>
                <input type="range" min="0" max={videoDuration || 0} step="0.1" value={trimEnd} onChange={(event) => updateTrimEnd(Number(event.target.value))} disabled={!videoReady || !videoDuration} aria-label="剪辑出点" />
              </label>
            </div>
            <div className="trim-ruler"><span>00:00.0</span><span>保留 {formatVideoTime(trimDuration)}</span><span>{formatVideoTime(videoDuration)}</span></div>
            <div className="clip-sequence" aria-label="视频拼接序列">
              <b>拼接序列 <small>{trimSegments.length ? `${trimSegments.length} 段 · ${formatVideoTime(sequenceDuration)}` : "未添加时直接导出当前选区"}</small></b>
              <div>
                {trimSegments.map((segment, index) => <article key={`${segment.start}-${segment.end}-${index}`}>
                  <button className="clip-select" onClick={() => selectTrimSegment(segment)} title="在预览中定位此片段"><i>{index + 1}</i><span>{formatVideoTime(segment.start)}–{formatVideoTime(segment.end)}</span></button>
                  <span className="clip-actions"><button onClick={() => moveTrimSegment(index, -1)} disabled={index === 0} aria-label={`片段 ${index + 1} 前移`}>←</button><button onClick={() => moveTrimSegment(index, 1)} disabled={index === trimSegments.length - 1} aria-label={`片段 ${index + 1} 后移`}>→</button><button onClick={() => removeTrimSegment(index)} aria-label={`删除片段 ${index + 1}`}>×</button></span>
                </article>)}
                {!trimSegments.length && <p>拖动时间轴选择范围，然后点击“加入拼接序列”</p>}
              </div>
              {trimSegments.length > 0 && <button className="clear-sequence" onClick={clearTrimSegments}>清空</button>}
            </div>
            <footer>
              <p className={trimError ? "error" : ""}>{trimMessage || (videoReady ? "序列为空时导出当前选区；有多个片段时按顺序拼接" : "等待视频生成完成")}</p>
              <div>{job?.edited_video_url && <a href={job.edited_video_url} download>下载已导出视频</a>}<button onClick={() => void exportVideoEdit()} disabled={!trimReady || trimBusy || (!editDirty && Boolean(job?.edited_video_url))}>{trimBusy ? "导出中…" : !editDirty && job?.edited_video_url ? "已导出" : trimSegments.length > 1 ? "拼接并导出" : "裁剪并导出"}</button></div>
            </footer>
          </section>

          {(error || job?.error || audioReady || videoReady) && <div className={`result-links ${error || job?.error ? "has-error" : ""}`}><b>{error || job?.error || (videoReady ? "视频已生成" : job?.reused ? "已复用历史结果，未重复调用付费接口" : "切片文本与音频已生成，可继续生成视频")}</b><span>{job?.audio_url && <a href={job.audio_url} target="_blank" rel="noreferrer">播放完整音频</a>}{job?.provider_audio_url && <a href={job.provider_audio_url} download="blabber-podcast.mp3">下载音频</a>}{job?.video_url && <a href={job.video_url}>下载视频</a>}{job?.edited_video_url && <a href={job.edited_video_url} download>下载剪辑片段</a>}</span></div>}
        </section>

        <aside className="assets-column">
          <button className="config-trigger" onClick={openConfig} title="配置豆包语音 PodcastTTS" aria-label="服务环境配置"><span>⚙</span>服务环境配置</button>
          <div className="asset-scroll">
            <section className="asset-section">
              <div className="background-grid">
                {backgrounds.map((item) => <button className={backgroundId === item.id ? "selected" : ""} onClick={() => setBackgroundId(item.id)} key={item.id}><img src={item.thumbnail ?? item.image} alt={item.name} /><i>✓</i></button>)}
              </div>
            </section>

            <section className="asset-section">
              <p className="section-help compact">最多选择两位；再次点击取消。第一位在左，第二位在右。</p>
              <div className="character-grid">
                {characters.map((item) => { const order = selectedCharacters.indexOf(item.id); return <button className={order >= 0 ? "selected" : ""} onClick={() => chooseCharacter(item.id)} key={item.id}><img src={item.image} alt={item.name} />{order >= 0 && <i>{order + 1}</i>}</button>; })}
              </div>
              {selected.map((item, index) => {
                const placement = placements[index] ?? defaultPlacements[index];
                return <div className="placement-card" key={item.id}>
                  <div><img src={item.image} alt="" /><span><b>{index === 0 ? "左侧" : "右侧"} · {item.name}</b><small>位置与大小</small></span></div>
                  <label>水平 <input type="range" min="0" max="70" value={placement.x} onChange={(event) => updatePlacement(index, "x", Number(event.target.value))} /><output>{placement.x}%</output></label>
                  <label>高度 <input type="range" min="-15" max="20" value={placement.y} onChange={(event) => updatePlacement(index, "y", Number(event.target.value))} /><output>{placement.y}</output></label>
                  <label>大小 <input type="range" min=".6" max="1.45" step=".01" value={placement.scale} onChange={(event) => updatePlacement(index, "scale", Number(event.target.value))} /><output>{Math.round(placement.scale * 100)}%</output></label>
                </div>;
              })}
            </section>

            <section className="asset-section">
              {([0, 1] as const).map((hostIndex) => {
                const character = selected[hostIndex];
                const voice = voices.find((item) => item.actionId === character?.actionId);
                return <div className="voice-select" key={hostIndex}>
                  <label>{hostIndex === 0 ? "Host A · 左侧" : "Host B · 右侧"}</label>
                  <div>{voice && <button className="selected" disabled><i style={{ borderColor: voice.color, color: voice.color }}>▶</i><span><b>{voice.name}</b><small>{voice.note} · 随角色自动匹配</small></span><Wave color={voice.color} /></button>}</div>
                </div>;
              })}
            </section>

            <section className="asset-section subtitle-controls" aria-label="字幕预览设置">
              <div className="section-title"><span><b>字</b>字幕预览</span><small>画面实时更新</small></div>
              <label className="subtitle-font-control">
                <span>字体</span>
                <select value={subtitleFontId} onChange={(event) => updateSubtitleFont(event.target.value)} aria-label="字幕字体">
                  {subtitleFonts.map((font) => <option value={font.id} key={font.id}>{font.name}{font.installed ? "" : "（需下载）"}</option>)}
                </select>
              </label>
              {!subtitleFontReady && selectedSubtitleFont?.downloadable && <button
                className="download-font"
                onClick={() => void downloadSubtitleFont(selectedSubtitleFont.id)}
                disabled={Boolean(fontBusy)}
              >{fontBusy === selectedSubtitleFont.id ? "正在下载…" : `下载 ${selectedSubtitleFont.name}${selectedSubtitleFont.size_mb ? ` · ${selectedSubtitleFont.size_mb}MB` : ""}`}</button>}
              <label className="subtitle-size-control">
                <span>大小</span>
                <input type="range" min="28" max="88" step="1" value={subtitleSize} onChange={(event) => updateSubtitleSize(Number(event.target.value))} aria-label="字幕大小" />
                <output>{subtitleSize}px</output>
              </label>
              <p className={fontMessage.includes("失败") ? "font-message error" : "font-message"}>{fontMessage || (subtitleFontReady ? "当前字体可用于预览和视频合成。" : "此字体尚未下载，预览暂用系统字体。")}</p>
            </section>
          </div>
        </aside>
      </section>
      {configOpen && <div className="config-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setConfigOpen(false)}>
        <section className="config-dialog" role="dialog" aria-modal="true" aria-label="服务环境变量配置">
          <header>
            <div><small>PODCAST TTS</small><h2>服务环境配置</h2><p>配置保存到本机 <code>mvp/.env</code>，密钥不会回显到网页。</p></div>
            <button onClick={() => setConfigOpen(false)} aria-label="关闭配置">×</button>
          </header>

          {config && <div className="service-status">
            <span className={config.services.podcast ? "ready" : "missing"}><i />豆包语音 PodcastTTS<b>{config.services.podcast ? "已配置" : "未填写 · 未配置"}</b></span>
          </div>}

          <div className="config-scroll">
            {configBusy && !config && <div className="config-loading">正在读取本地配置…</div>}
            {config && Array.from(new Set(config.fields.map((field) => field.group))).map((group) => <fieldset key={group}>
              <legend>{group} · <a href="https://console.volcengine.com/speech/app" target="_blank" rel="noreferrer">豆包语音控制台 ↗</a></legend>
              <div className="config-fields">
                {config.fields.filter((field) => field.group === group).map((field) => {
                  const markedForClear = clearConfigKeys.includes(field.key);
                  return <label className={field.secret ? "secret-field" : ""} key={field.key}>
                    <span>{field.label}{field.restart && <em>需重启</em>}</span>
                    <div>
                      <input
                        type={field.secret ? "password" : field.kind === "number" ? "number" : "text"}
                        step={field.kind === "number" ? "any" : undefined}
                        value={configValues[field.key] ?? ""}
                        placeholder={markedForClear ? "保存后清除" : field.secret && field.configured ? "已配置，留空保持原值" : field.default || "未配置"}
                        disabled={markedForClear}
                        onChange={(event) => {
                          setConfigValues((current) => ({ ...current, [field.key]: event.target.value }));
                          setClearConfigKeys((current) => current.filter((key) => key !== field.key));
                        }}
                      />
                      {field.secret && field.configured && <button type="button" className={markedForClear ? "undo" : "clear"} onClick={() => {
                        setConfigValues((current) => ({ ...current, [field.key]: "" }));
                        setClearConfigKeys((current) => markedForClear ? current.filter((key) => key !== field.key) : [...current, field.key]);
                      }}>{markedForClear ? "撤销" : "清除"}</button>}
                    </div>
                    <small>{field.help || field.key}</small>
                  </label>;
                })}
              </div>
            </fieldset>)}
          </div>

          <footer>
            <p className={configMessage.includes("失败") || configMessage.includes("无效") || configMessage.includes("必须") ? "error" : ""}>{configMessage || "PodcastTTS 需要豆包语音 App ID 与 Access Token。"}</p>
            <div><button className="secondary" onClick={() => setConfigOpen(false)}>取消</button><button className="primary" onClick={saveConfig} disabled={configBusy || !config}>{configBusy ? "处理中…" : "保存并应用"}</button></div>
          </footer>
        </section>
      </div>}
    </main>
  );
}
