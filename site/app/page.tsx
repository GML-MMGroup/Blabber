"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

type Speaker = "HostA" | "HostB";
type Turn = { speaker: Speaker; text: string };
type Episode = { topic: string; turns: Turn[] };
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
  error?: string;
  topic?: string;
  prompt?: string;
  created_at?: string;
  updated_at?: string;
  reused?: boolean;
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
  actionId: "dog" | "duck";
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

const backgrounds: Background[] = [
  { id: "zoo", name: "动物园直播间", image: "/scene-zoo.png", foreground: "/scene-zoo-foreground.png", accent: "#34a978" },
];

const characters: Character[] = [
  { id: "duck", name: "嘎嘎", image: "/funny-podcast-duck.png", actionPreview: "/action-preview-duck.png", actionId: "duck" },
  { id: "dog", name: "阿汪", image: "/funny-podcast-dog.png", actionPreview: "/action-preview-dog.png", actionId: "dog" },
];

const defaultPlacements: Placement[] = [
  { x: 15, y: 0, scale: 1.07 },
  { x: 45, y: 0, scale: 1 },
];

const voices: Voice[] = [
  { id: "podcast_duck", actionId: "duck", name: "嘎嘎专属", note: "PodcastTTS · 自动双声线", prompt: "青年女性卡通角色，普通话标准，声音清脆明亮、机灵俏皮；语气自信活泼，带自然笑意，吐字清楚，像反应敏捷的年轻播客主持人。", color: "#ff9254" },
  { id: "podcast_dog", actionId: "dog", name: "阿汪专属", note: "PodcastTTS · 自动双声线", prompt: "青年男性卡通角色，普通话标准，声音阳光清朗、热情有活力；语气忠诚友善又略带顽皮，节奏轻快，像幽默亲切的年轻播客主持人。", color: "#31b789" },
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

  const background = backgrounds.find((item) => item.id === backgroundId) ?? backgrounds[0];
  const selected = selectedCharacters.map((id) => characters.find((item) => item.id === id)).filter(Boolean) as Character[];
  const busy = Boolean(job && !["complete", "failed"].includes(job.status));
  const audioReady = Boolean(job?.audio_url);
  const videoReady = Boolean(job?.video_url) && !scriptDirty;
  const videoStage = Boolean(job?.stage?.startsWith("video"));
  const audioActive = Boolean(job && !audioReady && !videoStage && !["complete", "failed"].includes(job.status));
  const videoActive = Boolean(job && videoStage && !["complete", "failed"].includes(job.status));
  const videoWaiting = job?.stage === "video_waiting";
  const audioProgress = audioReady ? 100 : audioActive && job?.total ? Math.round((job.completed / job.total) * 100) : 0;
  const videoProgress = videoReady ? 100 : videoActive && job?.total ? Math.round((job.completed / job.total) * 100) : 0;

  const characterSet = "cartoon";

  useEffect(() => { void loadHistory(); }, []);

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

  function restoreHistory(item: Job) {
    setJob(item);
    if (item.episode) setEpisode(item.episode);
    setPrompt(item.topic || item.prompt || item.episode?.topic || "");
    setSourceFile(null);
    if (sourceFileInput.current) sourceFileInput.current.value = "";
    setError("");
    setScriptDirty(false);
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
          },
        }),
      });
      const next = await response.json();
      if (!response.ok) throw new Error(next.error || "播客任务创建失败");
      setEpisode(next.episode ?? { topic: documentBody?.topic || prompt, turns: [] });
      setJob(next);
      setScriptDirty(false);
      if (next.reused) void loadHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "播客任务创建失败");
    }
  }

  async function generateVideo() {
    if (!job?.id || !job.audio_url || selected.length < 2) return;
    setError("");
    try {
      const response = await fetch(`/api/mvp/jobs/${job.id}/video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "action",
          episode,
          force: scriptDirty,
          creative_config: {
            background: background.id,
            characters: selected.map((item) => item.actionId),
            placements,
          },
        }),
      });
      const next = await response.json();
      if (!response.ok) throw new Error(next.error || "视频任务创建失败");
      setJob(next);
      setScriptDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "视频任务创建失败");
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
              {job?.video_url ? (
                <video controls autoPlay={false} src={job.video_url}>浏览器不支持视频播放。</video>
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
              <div className="production-copy"><b>生成视频</b><small>{scriptDirty ? "脚本已修改，将同步更新字幕" : videoReady ? "成片已就绪" : videoWaiting ? "正在等待渲染资源" : videoActive ? `正在合成 · ${videoProgress}%` : audioReady ? "将语音、角色动作与场景合成" : "请先完成语音合成"}</small><progress value={videoProgress} max={100} /></div>
              <button onClick={generateVideo} disabled={busy || videoReady || !audioReady || selected.length < 2}>{scriptDirty ? "更新字幕并生成" : videoReady ? "视频已生成" : videoWaiting ? "排队中" : videoActive ? "生成中" : "生成视频"}</button>
            </article>
          </div>

          <div className="timeline-panel">
            <div className="ruler"><span>00:00</span><span>00:30</span><span>01:00</span><span>01:30</span><span>02:00</span></div>
            {(["HostA", "HostB"] as Speaker[]).map((speaker) => (
              <div className={`timeline-track ${speaker === "HostB" ? "purple" : ""}`} key={speaker}>
                <b><i />{speaker === "HostA" ? "Host A" : "Host B"}<small>VOICE</small></b>
                <div>{episode.turns.map((turn, index) => turn.speaker === speaker ? <span key={index} style={{ width: `${Math.min(27, Math.max(9, turn.text.length * .55))}%` }}><Wave color={speaker === "HostA" ? "#4f82ff" : "#865cff"} /></span> : <em key={index} />)}</div>
              </div>
            ))}
            <div className="camera-track"><b>▣<small>SCENE</small></b><div>{[0, 1, 2].map((item) => <span key={item}><img src={background.thumbnail ?? background.image} alt="" /></span>)}</div></div>
          </div>

          {(error || job?.error || audioReady || videoReady) && <div className={`result-links ${error || job?.error ? "has-error" : ""}`}><b>{error || job?.error || (videoReady ? "视频已生成" : job?.reused ? "已复用历史结果，未重复调用付费接口" : "切片文本与音频已生成，可继续生成视频")}</b><span>{job?.audio_url && <a href={job.audio_url}>播放完整音频</a>}{job?.provider_audio_url && <a href={job.provider_audio_url}>服务端音频</a>}{job?.video_url && <a href={job.video_url}>下载视频</a>}</span></div>}
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
