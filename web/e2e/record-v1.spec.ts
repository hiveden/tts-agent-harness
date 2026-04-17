/**
 * V1 录制脚本 — 核心痛点演示：shot02:1 的 4 次迭代
 *
 * 运行方式：
 *   cd web && npx playwright test ../scripts/record-v1.ts
 *
 * 产出：
 *   scripts/output/v1-recording.webm  — 录屏视频
 *   scripts/output/v1-subtitles.srt   — 字幕文件
 *
 * 后处理（烧入字幕）：
 *   ffmpeg -i scripts/output/v1-recording.webm \
 *     -vf "subtitles=scripts/output/v1-subtitles.srt:force_style='FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2'" \
 *     scripts/output/v1-final.mp4
 */

import { test } from "@playwright/test";
import { writeFileSync, mkdirSync } from "fs";
import { join } from "path";

const BASE_URL = "https://hiveden-tts.fly.dev";
const OUTPUT_DIR = join(__dirname, "../../scripts/output");
const CHUNK_ID = "smoke-test-script:shot02:1";

interface SubEntry {
  start: number;
  end?: number;
  text: string;
}

const subs: SubEntry[] = [];
let t0 = 0;

function mark(text: string) {
  const now = Date.now();
  if (subs.length > 0 && !subs[subs.length - 1].end) {
    subs[subs.length - 1].end = (now - t0) / 1000;
  }
  subs.push({ start: (now - t0) / 1000, text });
}

function toSRT(entries: SubEntry[]): string {
  return entries
    .map((e, i) => {
      const end = e.end ?? e.start + 3;
      const fmt = (s: number) => {
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        const ms = Math.floor((s % 1) * 1000);
        return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
      };
      return `${i + 1}\n${fmt(e.start)} --> ${fmt(end)}\n${e.text}\n`;
    })
    .join("\n");
}

test.use({
  viewport: { width: 1280, height: 800 },
  video: { mode: "on", size: { width: 1280, height: 800 } },
  launchOptions: { slowMo: 300 },
});

test("V1 — 核心痛点演示", async ({ page, context }) => {
  mkdirSync(OUTPUT_DIR, { recursive: true });
  t0 = Date.now();

  // S01: 打开页面
  mark("打开 TTS Harness — 已完成的 episode");
  await page.goto(BASE_URL);
  await page.waitForSelector("text=smoke-test-script", { timeout: 15000 });
  await page.click("text=smoke-test-script");
  await page.waitForTimeout(2000);

  // 滚动到 shot02:1
  // 定位到 shot02:1 行
  mark("定位到 shot02:1 — 原文含中英混合");
  const chunkRow = page.locator('[class*="grid"]').filter({ hasText: "shot02:1" }).first();
  await chunkRow.scrollIntoViewIfNeeded();
  await page.waitForTimeout(1500);

  // S02: 播放 take#1 — 原始版本
  mark('试听 take#1 — "第Ⅱ章"的 Ⅱ 被读成了"一"');
  const take1Play = chunkRow.locator("text=#1").locator("..").getByRole("button", { name: "▶" });
  await take1Play.click();
  await page.waitForTimeout(5000);
  await take1Play.click();
  await page.waitForTimeout(800);

  // S03: 播放 take#4 — 最终修正版
  mark("试听 take#4（最终版）— 修正后发音准确");
  const take4Play = chunkRow.locator("text=#4").locator("..").getByRole("button", { name: "▶" });
  await take4Play.click();
  await page.waitForTimeout(4500);
  await take4Play.click();
  await page.waitForTimeout(800);

  // S04: 展示编辑后的文本
  mark("TTS 源文本已调整为：第2章 / trans former（加空格断词）");
  const editBtn = chunkRow.getByRole("button", { name: "✎" });
  await editBtn.click();
  await page.waitForTimeout(3000);
  const closeBtn = page.getByRole("button", { name: "✕" }).first();
  await closeBtn.click();
  await page.waitForTimeout(1500);

  // S05: 结束
  mark("核心工作流：试听 → 发现问题 → 修改文本 → 重新合成 → 验证通过");
  await page.waitForTimeout(4000);

  // 结束字幕
  if (subs.length > 0 && !subs[subs.length - 1].end) {
    subs[subs.length - 1].end = (Date.now() - t0) / 1000;
  }

  // 保存字幕
  writeFileSync(join(OUTPUT_DIR, "v1-subtitles.srt"), toSRT(subs));

  // 视频由 Playwright 自动保存，需要关闭 context 后复制
  await page.close();
  const video = page.video();
  if (video) {
    const path = await video.path();
    if (path) {
      const { copyFileSync } = await import("fs");
      copyFileSync(path, join(OUTPUT_DIR, "v1-recording.webm"));
    }
  }
});
