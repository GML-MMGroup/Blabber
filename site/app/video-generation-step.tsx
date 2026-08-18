"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { InlineLoader } from "generative-loaders";
import "generative-loaders/styles.css";
import GenerationBeam from "./generation-beam";

type DirectoryHandleLike = {
  name: string;
  getFileHandle: (name: string, options: { create: boolean }) => Promise<{ createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> }>;
};

type VideoGenerationStepProps = {
  jobId?: string;
  videoUrl?: string;
  audioUrl?: string;
  coverUrl?: string;
  videoFileSize?: number;
  poster: string;
  previewContent: ReactNode;
  duration: number;
  updatedAt?: string;
  busy: boolean;
  progress: number;
  audioCompleted: number;
  audioTotal: number;
  videoCompleted: number;
  videoTotal: number;
  versions: Array<{ id: string; label: string }>;
  selectedVersionId: string;
  onSelectVersion: (id: string) => void;
  errorMessage: string;
  configChanged: boolean;
  canGenerate: boolean;
  onUseLatestConfig: () => void;
  onUseLatestVideo: () => void;
  onRegenerate: () => void;
};

const fallbackVideoMetadata = { resolution: "1920 × 1080 (16:9)", videoCodec: "H.264", bitrate: "4500 kbps", frameRate: "30 fps", audioCodec: "AAC", audioBitrate: "128 kbps" };
const resolutionValues: Record<string, string> = { "1920 × 1080 (16:9)": "1920x1080", "1280 × 720 (16:9)": "1280x720", "854 × 480 (16:9)": "854x480" };

function formatDuration(value: number) {
  const seconds = Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0;
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatBytes(value: number | null | undefined) {
  if (!value) return "生成后获取";
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

async function fetchBlob(url: string) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("文件读取失败");
  return response.blob();
}

async function saveBlob(blob: Blob, filename: string, directory?: DirectoryHandleLike | null) {
  if (directory) {
    const file = await directory.getFileHandle(filename, { create: true });
    const writable = await file.createWritable();
    await writable.write(blob);
    await writable.close();
    return;
  }
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function ConfigUpdateNotice({ updatedAt, busy, progress, canGenerate, onUseLatestConfig, onUseLatestVideo, onRegenerate }: Pick<VideoGenerationStepProps, "updatedAt" | "busy" | "progress" | "canGenerate" | "onUseLatestConfig" | "onUseLatestVideo" | "onRegenerate">) {
  return <section className="config-update-notice"><span className="notice-icon" aria-hidden="true" /><div><b>配置已更新，当前视频不是最新版本</b><small>编辑后需重新同步　{updatedAt ? new Date(updatedAt).toLocaleString("zh-CN") : "尚未生成视频"}</small></div><nav aria-label="视频版本操作"><button className="outline" onClick={onUseLatestConfig}><i className="switch-icon" aria-hidden="true" />切换至最新配置</button><button className="outline" onClick={onUseLatestVideo}><i className="layers-icon" aria-hidden="true" />切换至最新合成视频</button><GenerationBeam active={busy} borderRadius={8} className="config-generate-beam" size="sm"><button className="primary" onClick={onRegenerate} disabled={busy || !canGenerate}><i className="refresh-icon" aria-hidden="true" />{busy ? `生成中 ${progress}%` : "生成视频"}</button></GenerationBeam></nav></section>;
}

function VideoPreview({ props, previewContent, onDuration }: { props: VideoGenerationStepProps; previewContent: ReactNode; onDuration: (duration: number) => void }) {
  const audioRatio = props.audioTotal ? Math.min(1, props.audioCompleted / props.audioTotal) : 0;
  const videoRatio = props.videoTotal ? Math.min(1, props.videoCompleted / props.videoTotal) : 0;
  const totalPercent = Math.round(audioRatio * 50 + videoRatio * 50);
  const showGenerationStatus = props.busy && totalPercent < 100;
  return <section className="generation-preview-panel">
    <header className="generation-preview-header">
      <div className="generation-preview-title"><b>合成视频预览</b><small>AI 语音播客合成视频，支持预览与导出</small></div>
      <label className="generation-version-select"><span>历史版本</span><select value={props.selectedVersionId} onChange={(event) => props.onSelectVersion(event.target.value)} disabled={!props.versions.length}><option value="">当前配置</option>{props.versions.map((version) => <option value={version.id} key={version.id}>{version.label}</option>)}</select></label>
      <div className={`generation-stage-progress combined${showGenerationStatus ? " has-status" : ""}`} role="progressbar" aria-label="生成进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={totalPercent}>
        {showGenerationStatus && <div className="generation-progress-status" role="status" aria-live="polite"><InlineLoader variant="spark" size={24} /><span>{totalPercent < 50 ? "生成音频中" : "生成视频中"}</span></div>}
        <i><em style={{ width: `${totalPercent}%` }} /></i><output>{totalPercent}%</output>
      </div>
      <GenerationBeam active={props.busy} borderRadius={9} className="generation-header-beam" size="sm"><button className="generation-header-button" onClick={props.onRegenerate} disabled={props.busy || !props.canGenerate}>{props.busy ? "生成中" : "生成视频"}</button></GenerationBeam>
    </header>
    {props.videoUrl ? <video key={props.videoUrl} controls preload="metadata" onLoadedMetadata={(event) => onDuration(event.currentTarget.duration)}><source src={props.videoUrl} />浏览器不支持视频播放。</video> : <div className="preview-canvas generation-config-preview">{previewContent}</div>}
  </section>;
}
function VideoInfoPanel({ videoUrl, videoFileSize, duration, updatedAt }: Pick<VideoGenerationStepProps, "videoUrl" | "videoFileSize" | "duration" | "updatedAt">) {
  const [detectedSize, setDetectedSize] = useState<number | null>(null);
  useEffect(() => {
    if (!videoUrl || videoFileSize) return;
    let active = true;
    fetch(videoUrl, { headers: { Range: "bytes=0-0" } }).then((response) => {
      const match = response.headers.get("content-range")?.match(/\/(\d+)$/);
      return match ? Number(match[1]) : Number(response.headers.get("content-length")) || null;
    }).then((size) => active && setDetectedSize(size)).catch(() => active && setDetectedSize(null));
    return () => { active = false; };
  }, [videoUrl, videoFileSize]);
  const rows = [["时长", duration ? formatDuration(duration) : "生成后获取"], ["分辨率", fallbackVideoMetadata.resolution], ["文件大小", formatBytes(videoFileSize || detectedSize)], ["视频编码", fallbackVideoMetadata.videoCodec], ["码率", fallbackVideoMetadata.bitrate], ["帧率", fallbackVideoMetadata.frameRate], ["音频编码", fallbackVideoMetadata.audioCodec], ["音频码率", fallbackVideoMetadata.audioBitrate], ["合成时间", updatedAt ? new Date(updatedAt).toLocaleString("zh-CN") : "尚未生成"]];
  return <aside className="video-info-panel"><h3>视频信息</h3><dl>{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></aside>;
}

function VideoExportPanel({ jobId, videoUrl, directory, onChooseDirectory }: Pick<VideoGenerationStepProps, "jobId" | "videoUrl"> & { directory: DirectoryHandleLike | null; onChooseDirectory: () => void }) {
  const [resolution, setResolution] = useState("1920 × 1080 (16:9)");
  const [name, setName] = useState("blabber-podcast.mp4");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function exportVideo() {
    if (!videoUrl || !jobId) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/mvp/jobs/${jobId}/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resolution: resolutionValues[resolution] }) });
      const result = await response.json() as { video_url?: string; error?: string };
      if (!response.ok || !result.video_url) throw new Error(result.error || "视频导出失败");
      await saveBlob(await fetchBlob(result.video_url), name.trim() || "blabber-podcast.mp4", directory);
      setMessage("");
    } catch (error) { setMessage(error instanceof Error ? error.message : "视频导出失败"); } finally { setBusy(false); }
  }
  return <section className="video-export-panel"><header><span className="video-export-icon" aria-hidden="true" /><b>导出视频</b></header><div className="export-fields"><label><span>导出分辨率</span><select value={resolution} onChange={(event) => setResolution(event.target.value)}>{Object.keys(resolutionValues).map((item) => <option key={item}>{item}</option>)}</select></label><label className="export-path"><span>导出路径</span><div><input value={directory ? directory.name : "未选择（将使用浏览器下载）"} readOnly /><button type="button" onClick={onChooseDirectory}>选择文件夹</button></div></label><label className="export-name"><span>视频名称</span><input value={name} onChange={(event) => setName(event.target.value)} /></label><button className="export-main-button" onClick={() => void exportVideo()} disabled={!videoUrl || busy}><img src="/download.png" alt="" aria-hidden="true" />{busy ? "导出中…" : "导出视频"}</button></div>{message && <p className="export-status" aria-live="polite">{message}</p>}</section>;
}

function IndependentExports({ jobId, coverUrl, audioUrl, directory }: Pick<VideoGenerationStepProps, "jobId" | "coverUrl" | "audioUrl"> & { directory: DirectoryHandleLike | null }) {
  const [busy, setBusy] = useState("");
  async function exportCover() {
    if (!jobId) return;
    setBusy("cover");
    try {
      let url = coverUrl;
      if (!url) {
        const response = await fetch(`/api/mvp/jobs/${jobId}/cover`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const result = await response.json() as { cover_url?: string; error?: string };
        if (!response.ok || !result.cover_url) throw new Error(result.error || "封面生成失败");
        url = result.cover_url;
      }
      await saveBlob(await fetchBlob(url), "blabber-cover.png", directory);
    } finally { setBusy(""); }
  }
  async function exportAudio() { if (!audioUrl) return; setBusy("audio"); try { await saveBlob(await fetchBlob(audioUrl), "blabber-podcast.mp3", directory); } finally { setBusy(""); } }
  return <div className="independent-exports"><article className="cover-export"><span className="asset-export-icon" aria-hidden="true" /><div><b>导出封面</b><small>导出成片无字幕第一帧</small></div><button onClick={() => void exportCover()} disabled={!jobId || Boolean(busy)}>{busy === "cover" ? "导出中…" : "导出封面"}</button></article><article className="audio-export"><span className="asset-export-icon" aria-hidden="true" /><div><b>导出音频</b><small>导出视频的音频文件</small></div><button onClick={() => void exportAudio()} disabled={!audioUrl || Boolean(busy)}>{busy === "audio" ? "导出中…" : "导出音频"}</button></article></div>;
}

export default function VideoGenerationStep(props: VideoGenerationStepProps) {
  const [duration, setDuration] = useState(props.duration);
  const [directory, setDirectory] = useState<DirectoryHandleLike | null>(null);
  useEffect(() => { setDuration(props.duration); }, [props.jobId, props.duration]);
  async function chooseDirectory() {
    const picker = (window as unknown as { showDirectoryPicker?: () => Promise<DirectoryHandleLike> }).showDirectoryPicker;
    if (!picker) { alert("当前浏览器不支持目录选择，将在导出时使用浏览器默认下载目录。"); return; }
    try { setDirectory(await picker.call(window)); } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      alert(error instanceof Error ? `选择文件夹失败：${error.message}` : "选择文件夹失败，将使用浏览器默认下载目录。");
    }
  }
  const displayedDuration = duration || props.duration;
  return <section className="video-generation-step">{props.errorMessage && <div className="generation-error-alert" role="alert"><span aria-hidden="true" /><div><b>生成失败</b><p>{props.errorMessage}</p></div></div>}<div className="generation-media-grid"><VideoPreview props={props} previewContent={props.previewContent} onDuration={setDuration} /><VideoInfoPanel videoUrl={props.videoUrl} videoFileSize={props.videoFileSize} duration={displayedDuration} updatedAt={props.updatedAt} /></div><div className="generation-export-grid"><VideoExportPanel jobId={props.jobId} videoUrl={props.videoUrl} directory={directory} onChooseDirectory={() => void chooseDirectory()} /><IndependentExports jobId={props.jobId} coverUrl={props.coverUrl} audioUrl={props.audioUrl} directory={directory} /></div></section>;
}
