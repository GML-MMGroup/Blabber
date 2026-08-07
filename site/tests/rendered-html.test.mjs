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
  assert.match(html, /最多选择两位；再次点击取消。第一位在左，第二位在右/);
  assert.match(html, /复古图书馆/);
  assert.match(html, /海滨电台/);
  assert.match(html, /星际直播舱/);
  assert.match(html, /水墨茶室/);
  assert.match(html, /阳光男生/);
  assert.match(html, /活力女生/);
  assert.match(html, /阿汪/);
  assert.match(html, /嘎嘎/);
  assert.doesNotMatch(html, /3D Milo|3D Luna|黏土小熊猫|黏土小水獭|动漫男生|动漫女生|科技男生|科技女生|低多边形男生|低多边形女生/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/);
});

test("ships product metadata and project assets", async () => {
  const [layout, page, packageJson] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    access(new URL("../public/blabber-banner.png", import.meta.url)),
    access(new URL("../public/og.png", import.meta.url)),
    access(new URL("../public/scene-library-composite.jpg", import.meta.url)),
    access(new URL("../public/scene-seaside-composite.jpg", import.meta.url)),
    access(new URL("../public/scene-space-composite.jpg", import.meta.url)),
    access(new URL("../public/scene-ink-tea-composite.jpg", import.meta.url)),
    access(new URL("../public/action-preview-male.png", import.meta.url)),
    access(new URL("../public/action-preview-female.png", import.meta.url)),
    access(new URL("../public/action-preview-dog.png", import.meta.url)),
    access(new URL("../public/action-preview-duck.png", import.meta.url)),
  ]);

  assert.match(layout, /openGraph/);
  assert.match(layout, /twitter/);
  assert.match(layout, /og-studio\.png/);
  assert.match(page, /thumbnail \?\? item\.image/);
  assert.match(page, /scene-library-foreground\.png/);
  assert.match(page, /src=\{character\.actionPreview\}/);
  assert.match(page, /if \(current\.includes\(id\)\) return current\.filter/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(access(new URL("../app/_sites-preview/SkeletonPreview.tsx", import.meta.url)));
});
