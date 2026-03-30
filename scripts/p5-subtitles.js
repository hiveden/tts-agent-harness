#!/usr/bin/env node
/**
 * P5 — 字幕生成
 *
 * 复用 P3 WhisperX 时间戳，将原始文稿文本与精确时间戳组合，
 * 输出 per-shot subtitles.json，供 Remotion 消费。
 *
 * 关键：字幕文本用 text（原始文稿），时间戳用 WhisperX 转写对齐结果。
 *
 * Usage:
 *   node scripts/p5-subtitles.js --chunks <chunks.json> --transcripts <dir> --outdir <dir>
 */

const fs = require("fs");
const path = require("path");

// --- 参数解析 ---
const args = process.argv.slice(2);
let chunksPath = "";
let transcriptsDir = "";
let outdir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--chunks" && args[i + 1]) chunksPath = args[++i];
  else if (args[i] === "--transcripts" && args[i + 1]) transcriptsDir = args[++i];
  else if (args[i] === "--outdir" && args[i + 1]) outdir = args[++i];
}

if (!chunksPath || !transcriptsDir || !outdir) {
  console.error(
    "Usage: node p5-subtitles.js --chunks <chunks.json> --transcripts <dir> --outdir <dir>"
  );
  process.exit(1);
}

// =============================================================
// 字幕分行（每行不超过 20 汉字）
// =============================================================

const MAX_LINE_CHARS = 20;

const STRIP_PUNCT = /[\s，。、；：？！""''（）《》【】\-—…·,.;:?!()\[\]{}"'\/\\\u200b\u3000]/g;

/**
 * 将一段原始文本按句号/逗号/顿号分行，每行不超过 MAX_LINE_CHARS。
 * 超长 part 在空格或中英文边界处断行，不拆英文单词。
 */
function splitSubtitleLines(text) {
  const parts = text.split(/(?<=[。？！，、；,])/);
  const lines = [];
  let buffer = "";

  for (const part of parts) {
    if (buffer.length + part.length <= MAX_LINE_CHARS) {
      buffer += part;
    } else {
      if (buffer) lines.push(buffer);
      if (part.length > MAX_LINE_CHARS) {
        // 智能断行：在空格、中英文边界处切分，不拆英文单词
        let remaining = part;
        while (remaining.length > MAX_LINE_CHARS) {
          let cutAt = MAX_LINE_CHARS;
          // 优先在空格处切
          const spaceIdx = remaining.lastIndexOf(" ", MAX_LINE_CHARS);
          if (spaceIdx > MAX_LINE_CHARS * 0.4) {
            cutAt = spaceIdx + 1;
          } else {
            // 在中英文边界处切（英文后跟中文，或中文后跟英文）
            for (let j = MAX_LINE_CHARS; j > MAX_LINE_CHARS * 0.4; j--) {
              const cur = remaining[j] || "";
              const prev = remaining[j - 1] || "";
              const isChinese = (c) => /[\u4e00-\u9fff]/.test(c);
              if ((isChinese(prev) && /[a-zA-Z0-9]/.test(cur)) ||
                  (/[a-zA-Z0-9]/.test(prev) && isChinese(cur))) {
                cutAt = j;
                break;
              }
            }
          }
          lines.push(remaining.slice(0, cutAt));
          remaining = remaining.slice(cutAt);
        }
        if (remaining) lines.push(remaining);
        buffer = "";
      } else {
        buffer = part;
      }
    }
  }
  if (buffer) lines.push(buffer);

  // 过滤纯标点行：合并到前一行
  const filtered = [];
  for (const line of lines) {
    if (line.replace(STRIP_PUNCT, "").length === 0 && filtered.length > 0) {
      filtered[filtered.length - 1] += line;
    } else {
      filtered.push(line);
    }
  }

  return filtered;
}

// =============================================================
// Main
// =============================================================

function main() {
  const chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
  fs.mkdirSync(outdir, { recursive: true });

  // 按 shot 分组
  const shotMap = new Map();
  for (const chunk of chunks) {
    if (chunk.status !== "validated" && chunk.status !== "transcribed") continue;
    const shotId = chunk.shot_id;
    if (!shotMap.has(shotId)) shotMap.set(shotId, []);
    shotMap.get(shotId).push(chunk);
  }

  const allShotSubtitles = {};
  let totalSubs = 0;

  for (const [shotId, shotChunks] of shotMap) {
    const chunksSubs = [];

    for (const chunk of shotChunks) {
      const transcriptPath = path.join(transcriptsDir, `${chunk.id}.json`);
      if (!fs.existsSync(transcriptPath)) {
        console.error(`  [WARN] ${chunk.id}: transcript not found, skipping`);
        continue;
      }

      const transcript = JSON.parse(fs.readFileSync(transcriptPath, "utf-8"));

      // 用 WhisperX 的 segment 时间戳，文本用原始文稿
      // 策略：WhisperX segments 提供时间边界，原始文稿按行分配到这些时间窗口
      const segments = transcript.segments || [];
      const originalLines = splitSubtitleLines(chunk.text);

      if (segments.length === 0) {
        console.error(`  [WARN] ${chunk.id}: no segments in transcript`);
        continue;
      }

      // 收集所有 word-level 时间戳（跨 segments 展平）
      const allWords = [];
      for (const seg of segments) {
        if (Array.isArray(seg.words)) {
          for (const w of seg.words) {
            if (w.start != null && w.end != null) {
              allWords.push(w);
            }
          }
        }
      }

      const chunkStart = segments[0].start;
      const chunkEnd = segments[segments.length - 1].end;
      const chunkDuration = chunkEnd - chunkStart;

      // 生成 chunk 内相对时间戳（从 0 开始），P6 负责全局偏移
      const subtitles = [];

      if (allWords.length > 0) {
        // === 按内容字数加权分配 words ===
        // 短行（2字）分配少量 words，长行（20字）分配更多。
        // 用去标点后的字符数作为权重，按比例分配 allWords。
        const lineWeights = originalLines.map((l) => Math.max(1, l.replace(STRIP_PUNCT, "").length));
        const totalWeight = lineWeights.reduce((s, w) => s + w, 0);

        let wordCursor = 0;
        for (let li = 0; li < originalLines.length; li++) {
          const ratio = lineWeights[li] / totalWeight;
          const wordsForLine = Math.max(1, Math.round(ratio * allWords.length));
          const firstIdx = wordCursor;
          const lastIdx = Math.min(wordCursor + wordsForLine - 1, allWords.length - 1);

          if (firstIdx >= allWords.length) break;

          const lineStart = allWords[firstIdx].start - chunkStart;
          const lineEnd = allWords[lastIdx].end - chunkStart;

          subtitles.push({
            id: `sub_${String(totalSubs + subtitles.length + 1).padStart(3, "0")}`,
            text: originalLines[li],
            start: round3(Math.max(0, lineStart)),
            end: round3(Math.max(0, lineEnd)),
          });

          wordCursor = lastIdx + 1;
        }
      } else {
        // === Fallback：无 word-level 数据，线性按字数分配 ===
        const totalChars = originalLines.reduce((s, l) => s + l.length, 0);
        let cursor = 0;
        for (const line of originalLines) {
          const lineDuration = (line.length / totalChars) * chunkDuration;
          subtitles.push({
            id: `sub_${String(totalSubs + subtitles.length + 1).padStart(3, "0")}`,
            text: line,
            start: round3(cursor),
            end: round3(cursor + lineDuration),
          });
          cursor += lineDuration;
        }
      }

      chunksSubs.push({
        chunk_id: chunk.id,
        subtitles,
      });
      totalSubs += subtitles.length;
    }

    allShotSubtitles[shotId] = { chunks: chunksSubs };
    const shotSubCount = chunksSubs.reduce((s, c) => s + c.subtitles.length, 0);
    console.log(`  ${shotId}: ${shotSubCount} subtitle lines (${chunksSubs.length} chunks)`);
  }

  // 输出
  const outPath = path.join(outdir, "subtitles.json");
  fs.writeFileSync(outPath, JSON.stringify(allShotSubtitles, null, 2));
  console.log(`\n=== Output: ${outPath} (${totalSubs} lines across ${shotMap.size} shots) ===`);
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

main();
