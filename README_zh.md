<div align="center">

<!-- 👇 在这里替换成你的封面 Banner 图 -->
<img src="./assets/banner.png" alt="Blabber Banner" width="100%" />

# Blabber 🎙️

### 首个 Agentic 播客视频生成平台

**一句提示词，生成一整期动画播客节目 — 对白、配音、口型、运镜、成片，全流程自动化。**

[![Stars](https://pfst.cf2.poecdn.net/base/image/c71a5553a5914ff023b4ec0e52df729b1786fd430f7563c6eb700b1ee44b6a02?pmaid=639576682)](https://github.com/GML-MMGroup/Blabber)
[![Version](https://pfst.cf2.poecdn.net/base/image/d8617c7287e62a79e87bf1290fad68c5779fb435e813c276f13163b85354c97c?pmaid=639576684)](https://github.com/GML-MMGroup/Blabber/releases)

[English](./README.md) · **简体中文** · [在线体验](#) · [文档](#)

</div>

---

## 🎬 产品宣传片

<!-- 产品宣传片待发布。 -->

> 只需输入一句话 — *"做一期关于咖啡文化的播客"* — Blabber 就会自动编写对白、安排两位主持人、逐句配音、将口型逐帧对齐音频波形、规划运镜切换，并渲染出最终成片。**你描述节目，Agent 负责制作。**

---

## 📰 最新动态

- **[2026-07-21]** 🎉 Blabber 正式登陆 GitHub！
- **[2026-08-07]** 🚀 发布第一版，内置动物园场景与嘎嘎、阿汪两个可生成视频的角色。
- **[2026-08-20]** ✨ 相较 8 月 7 日首版，新增 Luna、Milo 与更多场景，升级双主持音色控制和脚本、字幕、时间线编辑，并加入分段并行合成、生成进度反馈、局域网部署及音画同步稳定性优化。

<!-- 后续更新持续追加到这里 -->

---

## 🌟 案例展示 — 覆盖多种题材

> 以下是 6 期 Blabber 真实生成的动画播客节目，每段展示 12 秒。

<table>
<tr>
<td width=33% align=center>
<strong>🧚 童话故事</strong>

https://github.com/user-attachments/assets/6274e261-fea9-4d0d-add0-4d51e6aa4584

</td>
<td width=33% align=center>
<strong>💞 当代爱情观</strong>

https://github.com/user-attachments/assets/58d03bf6-3e9e-4d61-b20f-d42436f3f094

</td>
<td width=33% align=center>
<strong>🗣️ 低情商行为</strong>

https://github.com/user-attachments/assets/06caadb8-45d2-446a-a4e2-08f43bdbbb83

</td>
</tr>
<tr>
<td width=33% align=center>
<strong>🎬 电影评论</strong>

https://github.com/user-attachments/assets/08e88909-3efe-43a3-ba24-dfed05e11209

</td>
<td width=33% align=center>
<strong>☕ 咖啡文化</strong>

https://github.com/user-attachments/assets/3ed13a6b-0850-4b57-b7ab-07f900d278a6

</td>
<td width=33% align=center>
<strong>🚗 新款汽车</strong>

https://github.com/user-attachments/assets/1347eb74-3b3b-48f0-8e8a-27179794001a

</td>
</tr>
</table>

---

## 💡 Blabber 是什么？

Blabber 是一个**专为播客视频创作打造的 AI 生产平台**。你不需要录音、不需要做动画、也不需要剪辑 — 只需描述你想要的节目，一支 AI Agent 团队就会编排整个制作流程：**选题策划 → 对白脚本 → 音色选角 → 语音合成 → 口型同步 → 运镜编排 → 剪辑 → 最终渲染。**

它不是"一键出片就结束"的生成器。Blabber 会把每期节目变成一个**可编辑的工程项目**：生成之后，你可以继续打磨任何细节 — 一句台词、一位主持人的音色、一个镜头切换、一处场景 — 既可以在内置的 AI Copilot 对话框里说出来，也可以直接在片段式时间线上动手改。

---

## ✨ 核心功能

- **端到端生成** — 输入一句提示词或一份文档，自动完成双主持脚本、配音、动画、字幕、运镜和最终成片。
- **自然双人对谈** — 生成匹配角色的声线、回应和追问，并将每句音频拆分为可编辑片段。
- **自动化视觉制作** — 逐帧口型同步、说话人感知运镜与 FFmpeg 成片合成。
- **对话式编辑** — 通过 AI Copilot 或片段式时间线修改脚本、音色、镜头和节奏，支持候选版本与历史回滚。
- **灵活组合与发布** — 自由搭配内置角色和场景，导出带字幕的横屏、竖屏或方形视频。

---

## 🏗️ 工作原理
💡 提示词 → 🎬 节目策划 → ✍️ 对白脚本 → 🎙️ 语音演绎
↓
🚀 最终成片 ← 🎞️ 合成 ← 🎵 声音 ← 🎥 运镜编排 ← 👄 口型同步

全流程由 AI Agent 编排，可在内置编辑器中随时修改。

---

## 🛠️ 本地完整安装

环境要求：

- Git
- Node.js `>=22.13.0`
- Python `>=3.9`
- `ffmpeg` 与 `ffprobe` 可在终端直接运行，并包含 `libvpx-vp9` 支持
- 至少约 1 GB 可用磁盘空间，用于运行缓存和视频输出。随仓库发布的
  VP9 Alpha 动作素材约 52 MB，会由普通 Git clone 直接下载，不需要
  Git LFS。

首次安装：

```bash
git clone https://github.com/GML-MMGroup/Blabber.git
cd Blabber

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r mvp/requirements.txt
cp mvp/.env.example mvp/.env

cd site
npm ci
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活虚拟环境，并用
`Copy-Item mvp/.env.example mvp/.env` 创建配置文件。

如果 PowerShell 的执行策略阻止运行 `npm.ps1`，请将文档中的 npm 命令改用 `npm.cmd`（例如 `npm.cmd ci`、`npm.cmd run dev`）。安装前可分别执行 `node --version`、`python --version`、`ffmpeg -version` 和 `ffprobe -version` 验证依赖是否已加入 `PATH`。 视频片段会并行渲染：动作视频默认最多 4 个任务，唇形视频默认最多 2 个任务。可在 `mvp/.env` 中将 `BLABBER_VIDEO_WORKERS` 设为正整数以统一覆盖；CPU、内存或显存紧张时请调低。

网页已接入火山引擎 PodcastTTS：一次 API 请求直接返回双主持切片文本、逐切片 MP3 与完整 MP3，并可继续生成真实 MP4。首次安装完成后，分别打开两个终端。

终端一（后端）：

```bash
cd Blabber
source .venv/bin/activate
cd site
npm run dev:mvp
```

终端二（前端）：

```bash
cd Blabber
cd site
npm run dev
```

然后访问终端显示的本地地址（默认 `http://localhost:3000`）。在“服务环境配置”中填写豆包语音 PodcastTTS 的 App ID 与 Access Token。需要使用 Seedream/Seedance 时，再执行 `python -m pip install -r mvp/requirements-ark.txt`，并在 `mvp/.env` 中填写可选的 `ARK_API_KEY`。密钥文件已被 Git 忽略，请勿提交。

输入主题或传入文档后点击“生成脚本和音频”，页面会显示 PodcastTTS 返回的切片文本与音频进度；音频完成后可以继续使用嘎嘎和阿汪在动物园场景中生成 MP4。

---

## 🚀 生产部署

`site/` 已配置为 OpenAI Sites 项目。发布前请在该目录执行 `npm ci` 和 `npm test`。仓库中的 `.openai/hosting.json` 已记录现有 Sites 项目标识，请勿自行替换 `project_id`。 发布前请压缩被 Git 跟踪的大型静态资源；超大图片或过大的源码传输包可能导致 Sites 拒绝源码推送。

Sites 只发布网页与 Worker。`mvp/` 下的 Python 服务负责 PodcastTTS 调用、媒体持久化、FFmpeg 处理和 MP4 渲染，**不会**随 Sites 一起部署。`site/vite.config.ts` 中 `/api/mvp` 与 `/mvp-media` 到 `127.0.0.1:8787` 的代理仅在本地开发时生效。因此，要让公网版本具备完整生成功能，还需单独托管 Python 后端，并通过生产反向代理（或等效的同源路由）转发这两个路径。请勿公开 `mvp/.env`，也不要把 API 密钥放入前端环境变量。

---

## 📚 文档接入接口

`POST /api/mvp/document-jobs` 使用 PodcastTTS 的文档模式（`action=0`），支持传入网页/可下载文档 URL、长文本或本地文件。前端可直接选择 `.txt`、`.md`、`.html`、`.json`、`.csv`、`.docx`、`.pdf` 文件（最大 20 MB），选中文件后会显示文件名和大小：

```bash
curl -X POST http://127.0.0.1:8787/api/mvp/document-jobs \
  -H 'Content-Type: application/json' \
  -d '{"input_url":"https://example.com/article","topic":"文章解读"}'
```

也可以将请求体改为 `{"input_text":"文档正文……","topic":"文档解读"}`，或上传 Base64 文件：`{"file_name":"report.pdf","file_base64":"...","topic":"报告解读"}`。`input_url`、`input_text` 和文件上传三种来源必须且只能提供一种。扫描版 PDF 需要先进行 OCR。接口返回 `202` 和任务 ID，通过 `GET /api/mvp/jobs/{id}` 查询；完成后响应包含 `episode.turns`、`clips[].audio_url`、`audio_url` 和 `provider_audio_url`。

生成任务会持久化到 `mvp/output/jobs-history.json`，`GET /api/mvp/history` 可读取最近记录。前端可以直接恢复已有脚本、切片音频和视频；相同的新输入会复用已完成结果，不再重复调用付费接口。生成过程中，`GET /api/mvp/jobs/{id}/events` 通过 SSE 实时推送累计脚本切片和音频切片。

<div align="center">

**⭐ 如果 Blabber 对你有帮助，欢迎点个 Star 支持！**

Made with ❤️ by the Blabber Team

</div>
