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

// --- 配置 ---
const MAX_CHARS_PER_CHUNK = 200;
const MAX_SENTENCES_PER_CHUNK = 5;
const MIN_SENTENCES_PER_CHUNK = 2;

// --- 参数解析 ---
const args = process.argv.slice(2);
let scriptPath = "";
let outdir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--script" && args[i + 1]) scriptPath = args[++i];
  else if (args[i] === "--outdir" && args[i + 1]) outdir = args[++i];
}

if (!scriptPath || !outdir) {
  console.error(
    "Usage: node p1-chunk.js --script <script.json> --outdir <dir>"
  );
  process.exit(1);
}

// =============================================================
// 文本规范化（TTS 预处理）
// =============================================================

function normalize(text) {
  let t = text;

  // 删除导演标注 [...] 和停顿标记
  t = t.replace(/\[.*?\]/g, "");
  t = t.replace(/（停顿.*?）/g, "");
  t = t.replace(/\(停顿.*?\)/g, "");

  // 特殊符号替换
  // 英文连字符 → 空格（yoyo-evolve → yoyo evolve, Natural-Language → Natural Language）
  t = t.replace(/([a-zA-Z])-([a-zA-Z\u4e00-\u9fff])/g, "$1 $2");
  // 数字范围 dash → 到（排除日期格式 YYYY-MM-DD）
  t = t.replace(/(?<!\d)(\d{1,3})\s*-\s*(\d{1,5})(?![/-]\d)/g, "$1到$2"); // 28-35 → 28到35
  t = t.replace(/(\d+)%/g, "百分之$1"); // 53% → 百分之53

  // 英文品牌名后加句号隔断（中英交界）
  t = t.replace(/([a-zA-Z]{2,})([\u4e00-\u9fff])/g, "$1. $2");

  return t.replace(/\s+/g, " ").trim();
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
    chunks.push({
      id: `${shotId}_chunk${String(chunks.length + 1).padStart(2, "0")}`,
      shot_id: shotId,
      text: text,
      text_normalized: normalize(text),
      sentence_count: buffer.length,
      char_count: text.length,
      status: "pending",
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
    const text = seg.tts_text || seg.text || seg.narration || "";

    if (!text) {
      console.log(`  [SKIP] ${shotId} — no text`);
      continue;
    }

    const sentences = splitSentences(text);
    const chunks = packChunks(sentences, shotId);

    console.log(
      `  ${shotId}: ${text.length} chars → ${chunks.length} chunk(s) [${chunks.map((c) => c.sentence_count + "句").join(", ")}]`
    );

    allChunks.push(...chunks);
  }

  // 写入 chunks.json
  const outPath = path.join(outdir, "chunks.json");
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
  let ci = 0;
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
