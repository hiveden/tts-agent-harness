#!/usr/bin/env node
/**
 * P1 — 智能切分
 *
 * 读取 script.json，按 shot 为一级单元，在 shot 内按句子做二级切分。
 * 输出 chunks.json，保留 text（原文，用于字幕）和 text_normalized（TTS 输入）。
 *
 * Usage:
 *   node scripts/p1-chunk.js --script <script.json> --outdir <dir>
 */

const fs = require("fs");
const path = require("path");

// --- 参数解析 ---
const args = process.argv.slice(2);
let scriptPath = "";
let outdir = "";
let harnessDir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--script" && args[i + 1]) scriptPath = args[++i];
  else if (args[i] === "--outdir" && args[i + 1]) outdir = args[++i];
  else if (args[i] === "--harness-dir" && args[i + 1]) harnessDir = args[++i];
}

if (!scriptPath || !outdir) {
  console.error(
    "Usage: node p1-chunk.js --script <script.json> --outdir <dir> [--harness-dir <dir>]"
  );
  process.exit(1);
}

// --- .harness 目录 ---
const defaultHarnessDir = path.resolve(__dirname, "..");
const resolvedHarnessDir = harnessDir || defaultHarnessDir;

// --- 配置（从 config.json 加载，回退到默认值）---
let MAX_CHARS_PER_CHUNK = 200;
let MAX_SENTENCES_PER_CHUNK = 5;
let MIN_SENTENCES_PER_CHUNK = 2;

const configPath = path.join(resolvedHarnessDir, ".harness", "config.json");
try {
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  if (config.p1) {
    MAX_CHARS_PER_CHUNK = config.p1.max_chars_per_chunk ?? MAX_CHARS_PER_CHUNK;
    MAX_SENTENCES_PER_CHUNK = config.p1.max_sentences_per_chunk ?? MAX_SENTENCES_PER_CHUNK;
    MIN_SENTENCES_PER_CHUNK = config.p1.min_sentences_per_chunk ?? MIN_SENTENCES_PER_CHUNK;
  }
} catch {
  // config.json 不存在或格式错误，使用默认值
}

// =============================================================
// 文本规范化（TTS 预处理）
// =============================================================

function normalize(text) {
  // S2-Pro 场景：P1 只做切分，不做内容修改。脚本原文直接传 TTS。
  return text.replace(/\s+/g, " ").trim();
}

// =============================================================
// 句子切分
// =============================================================

/**
 * 按中文句号、问号、感叹号、分号切分，保留分隔符
 */
function splitSentences(text) {
  const parts = text.split(/(?<=[。？！；\n])/);
  return parts.map((s) => s.trim()).filter((s) => s.length > 0);
}

/**
 * 将句子列表按规则打包成 chunks
 */
function packChunks(sentences, shotId) {
  const chunks = [];
  let buffer = [];
  let bufferLen = 0;

  function flush() {
    if (buffer.length === 0) return;
    const text = buffer.join("");
    const normalized = normalize(text);
    chunks.push({
      id: `${shotId}_chunk${String(chunks.length + 1).padStart(2, "0")}`,
      shot_id: shotId,
      text: text,
      text_normalized: normalized,
      sentence_count: buffer.length,
      char_count: text.length,
      status: "pending",
      normalized_history: [
        { round: 0, value: normalized, source: "p1-normalize", ts: new Date().toISOString() }
      ],
    });
    buffer = [];
    bufferLen = 0;
  }

  for (const sentence of sentences) {
    // 如果加入后超限，且 buffer 已有内容，先 flush
    if (
      buffer.length > 0 &&
      (buffer.length >= MAX_SENTENCES_PER_CHUNK ||
        bufferLen + sentence.length > MAX_CHARS_PER_CHUNK)
    ) {
      flush();
    }
    buffer.push(sentence);
    bufferLen += sentence.length;
  }
  flush();

  // 最小片段保护：如果最后一个 chunk 只有 1 句且前面有 chunk，
  // 合并到前一个（但不超过 MAX_CHARS 的 1.5 倍，避免产出过长 chunk）
  if (
    chunks.length > 1 &&
    chunks[chunks.length - 1].sentence_count < MIN_SENTENCES_PER_CHUNK
  ) {
    const last = chunks[chunks.length - 1];
    const prev = chunks[chunks.length - 2];
    const mergedLen = prev.char_count + last.char_count;
    if (mergedLen <= MAX_CHARS_PER_CHUNK * 1.5) {
      chunks.pop();
      const merged = prev.text + last.text;
      prev.text = merged;
      prev.text_normalized = normalize(merged);
      prev.sentence_count += last.sentence_count;
      prev.char_count = merged.length;
      prev.normalized_history = [
        { round: 0, value: prev.text_normalized, source: "p1-normalize", ts: new Date().toISOString() }
      ];
    }
  }

  return chunks;
}

// =============================================================
// Main
// =============================================================

function main() {
  const script = JSON.parse(fs.readFileSync(scriptPath, "utf-8"));
  const segments = script.segments || script.shots || [];

  if (segments.length === 0) {
    console.error("No segments found in script");
    process.exit(1);
  }

  fs.mkdirSync(outdir, { recursive: true });

  const allChunks = [];

  for (const seg of segments) {
    const shotId = typeof seg.id === "number"
      ? `shot${String(seg.id).padStart(2, "0")}`
      : seg.id;
    const ttsText = seg.tts_text || seg.text || seg.narration || "";
    const subtitleText = seg.text || seg.narration || "";

    if (!ttsText) {
      console.log(`  [SKIP] ${shotId} — no text`);
      continue;
    }

    const sentences = splitSentences(ttsText);
    const chunks = packChunks(sentences, shotId);

    // 如果有独立的字幕文本（seg.text ≠ seg.tts_text），存到 subtitle_text
    if (seg.tts_text && subtitleText && subtitleText !== ttsText) {
      // 按 chunk 数量均匀分配字幕文本（按句号切分对齐）
      const subSentences = splitSentences(subtitleText);
      const perChunk = Math.ceil(subSentences.length / chunks.length);
      for (let ci = 0; ci < chunks.length; ci++) {
        chunks[ci].subtitle_text = subSentences.slice(ci * perChunk, (ci + 1) * perChunk).join("");
      }
    }

    console.log(
      `  ${shotId}: ${ttsText.length} chars → ${chunks.length} chunk(s) [${chunks.map((c) => c.sentence_count + "句").join(", ")}]`
    );

    allChunks.push(...chunks);
  }

  // 写入 chunks.json（合并已有运行时数据：duration_s, file, status 等）
  const outPath = path.join(outdir, "chunks.json");
  let existingChunks = [];
  try {
    existingChunks = JSON.parse(fs.readFileSync(outPath, "utf-8"));
  } catch {}
  const existingMap = new Map(existingChunks.map((c) => [c.id, c]));

  for (const chunk of allChunks) {
    const existing = existingMap.get(chunk.id);
    if (existing) {
      // 保留运行时字段，只更新 P1 产出的字段
      if (existing.duration_s != null) chunk.duration_s = existing.duration_s;
      if (existing.file) chunk.file = existing.file;
      if (existing.status && existing.status !== "pending") {
        // 如果 text_normalized 变了，重置 status 触发重做
        if (existing.text_normalized === chunk.text_normalized) {
          chunk.status = existing.status;
        }
        // text_normalized 变了则保持 pending，让 P2 重做
      }
    }
  }

  fs.writeFileSync(outPath, JSON.stringify(allChunks, null, 2));

  console.log(`\n=== Output: ${outPath} ===`);
  console.log(`  Total chunks: ${allChunks.length}`);
  console.log(
    `  Total chars: ${allChunks.reduce((s, c) => s + c.char_count, 0)}`
  );

  // 可逆性校验
  const segTexts = segments
    .map((s) => s.tts_text || s.text || s.narration || "")
    .filter(Boolean);
  const reconstructed = [];
  for (const seg of segments) {
    const shotId = typeof seg.id === "number"
      ? `shot${String(seg.id).padStart(2, "0")}`
      : seg.id;
    const shotChunks = allChunks.filter((c) => c.shot_id === shotId);
    reconstructed.push(shotChunks.map((c) => c.text).join(""));
  }

  const original = segTexts.join("");
  const rebuilt = reconstructed.join("");
  if (original === rebuilt) {
    console.log("  ✓ 可逆性校验通过");
  } else {
    console.error("  ✗ 可逆性校验失败！切分后无法还原原始文本");
    process.exit(1);
  }
}

main();
