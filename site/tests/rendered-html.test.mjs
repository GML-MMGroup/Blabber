import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html", host: "localhost" },
    }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Blabber landing page", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/);
  assert.match(html, /<title>Blabber Studio — 动画播客制作工作台<\/title>/);
  assert.match(html, /描述你想制作的节目/);
  assert.match(html, /生成脚本和音频/);
  assert.match(html, /播客生成状态/);
  assert.match(html, /video-generate-button/);
  assert.match(html, /字幕预览/);
  assert.match(html, /思源黑体/);
  assert.match(html, /字幕大小/);
  assert.match(html, /视频裁剪与拼接/);
  assert.match(html, /生成视频后可裁剪、排序并拼接片段/);
  assert.match(html, /拼接序列/);
  assert.match(html, /最多选择两位；再次点击取消。第一位在左，第二位在右/);
  assert.match(html, /阿汪/);
  assert.match(html, /嘎嘎/);
  assert.match(html, /俏皮女声 2\.0/);
  assert.match(html, /温暖阿虎 2\.0/);
  assert.match(html, /动物园直播间/);
  assert.doesNotMatch(html, /深夜播客间|复古图书馆|海滨电台/);
  assert.doesNotMatch(html, /阳光男生|活力女生|动漫男生|动漫女生/);
  assert.doesNotMatch(html, /3D Milo|3D Luna|黏土小熊猫|黏土小水獭/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/);
});

test("ships product metadata and project assets", async () => {
  const [layout, page, packageJson, apiServer] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../../mvp/api_server.py", import.meta.url), "utf8"),
    access(new URL("../public/blabber-banner.png", import.meta.url)),
    access(new URL("../public/og.png", import.meta.url)),
    access(new URL("../public/scene-zoo.png", import.meta.url)),
    access(new URL("../public/scene-zoo-foreground.png", import.meta.url)),
    access(new URL("../public/action-preview-dog.png", import.meta.url)),
    access(new URL("../public/action-preview-duck.png", import.meta.url)),
  ]);

  assert.match(layout, /openGraph/);
  assert.match(layout, /twitter/);
  assert.match(layout, /og-studio\.png/);
  assert.match(page, /thumbnail \?\? item\.image/);
  assert.match(page, /scene-zoo-foreground\.png/);
  assert.match(page, /src=\{character\.actionPreview\}/);
  assert.match(page, /if \(current\.includes\(id\)\) return current\.filter/);
  assert.match(page, /href=\{job\.audio_url\} target="_blank" rel="noreferrer">播放完整音频/);
  assert.match(page, /href=\{job\.provider_audio_url\} download="blabber-podcast\.mp3">下载音频/);
  assert.match(page, /fetch\("\/api\/mvp\/fonts"\)/);
  assert.match(page, /\/api\/mvp\/fonts\/\$\{fontId\}\/download/);
  assert.match(page, /subtitles: \{ font: subtitleFontId, size: subtitleSize \}/);
  assert.match(page, /\/api\/mvp\/jobs\/\$\{job\.id\}\/video\/edit/);
  assert.match(page, /拼接并导出/);
  assert.match(page, /video-button-sheen/);
  assert.match(page, /Math\.max\(0, Math\.min\(99/);
  for (const voiceType of [
    "zh_female_qiaopinv_uranus_bigtts",
    "zh_male_wennuanahu_uranus_bigtts",
  ]) {
    assert.match(page, new RegExp(voiceType));
    assert.match(apiServer, new RegExp(voiceType));
  }
  assert.match(apiServer, /path == "\/api\/mvp\/fonts"/);
  assert.match(apiServer, /subtitle_font_size=subtitle_config\["size"\]/);
  assert.match(apiServer, /video_edit_match = re\.fullmatch/);
  assert.match(apiServer, /def _trim_video/);
  assert.match(apiServer, /def _edit_video/);
  assert.match(apiServer, /stage="video_prepare", completed=0, total=1/);
  assert.doesNotMatch(apiServer, /stage="video", completed=1, total=2/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
