#!/usr/bin/env node
/**
 * P6 — 音频拼接 + Crossfade
 *
 * 将同一 shot 的多个 chunk 音频拼接为一个 WAV，
 * 段落内 crossfade，段落间静音间隔。
 * 同时更新 subtitles.json 的全局偏移。
 *
 * Usage:
 *   node scripts/p6-concat.js --chunks <chunks.json> --audiodir <dir> --subtitles <subtitles.json> --outdir <dir>
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

// --- 配置 ---
const CHUNK_GAP_MS = 50;           // 段落内 chunk 间静音间隔
const PARAGRAPH_GAP_MS = 200;     // 段落间静音
const PADDING_MS = 200;           // 首尾 padding

// --- 参数解析 ---
const args = process.argv.slice(2);
let chunksPath = "";
let audiodir = "";
let subtitlesPath = "";
let outdir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--chunks" && args[i + 1]) chunksPath = args[++i];
  else if (args[i] === "--audiodir" && args[i + 1]) audiodir = args[++i];
  else if (args[i] === "--subtitles" && args[i + 1]) subtitlesPath = args[++i];
  else if (args[i] === "--outdir" && args[i + 1]) outdir = args[++i];
}

if (!chunksPath || !audiodir || !subtitlesPath || !outdir) {
  console.error(
    "Usage: node p6-concat.js --chunks <chunks.json> --audiodir <dir> --subtitles <subtitles.json> --outdir <dir>"
  );
  process.exit(1);
}

// =============================================================
// ffmpeg helpers
// =============================================================

function getAudioDuration(filePath) {
  const out = execSync(
    `ffprobe -v quiet -show_entries format=duration -of csv=p=0 "${filePath}"`,
    { encoding: "utf-8" }
  );
  return parseFloat(out.trim());
}

/**
 * 拼接多个 WAV → 单个 WAV，使用 ffmpeg concat filter
 * 简单方案：先生成静音 padding，然后用 concat 协议拼接
 */
function concatWavFiles(wavPaths, outputPath) {
  if (wavPaths.length === 0) return;

  if (wavPaths.length === 1) {
    // 单个 chunk：生成 padding WAV，用 concat demuxer 拼接
    const paddingPath = path.resolve(outputPath + ".padding.wav");
    const listPath = path.resolve(outputPath + ".list.txt");
    const absOutput = path.resolve(outputPath);
    execSync(
      `ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t ${PADDING_MS / 1000} "${paddingPath}" 2>/dev/null`
    );
    fs.writeFileSync(listPath, [
      `file '${paddingPath}'`,
      `file '${path.resolve(wavPaths[0])}'`,
      `file '${paddingPath}'`,
    ].join("\n"));
    execSync(
      `ffmpeg -y -f concat -safe 0 -i "${listPath}" -ar 44100 -ac 1 "${absOutput}" 2>/dev/null`
    );
    [listPath, paddingPath].forEach((f) => { try { fs.unlinkSync(f); } catch {} });
    return;
  }

  // 多个 chunk：用 concat demuxer
  const listPath = path.resolve(outputPath + ".list.txt");
  const paddingPath = path.resolve(outputPath + ".padding.wav");
  const gapPath = path.resolve(outputPath + ".gap.wav");

  // 生成 padding 和 gap 静音
  execSync(
    `ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t ${PADDING_MS / 1000} "${paddingPath}" 2>/dev/null`
  );
  execSync(
    `ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t ${CHUNK_GAP_MS / 1000} "${gapPath}" 2>/dev/null`
  );

  // 构建 concat 列表
  const lines = [`file '${paddingPath}'`];
  for (let i = 0; i < wavPaths.length; i++) {
    lines.push(`file '${path.resolve(wavPaths[i])}'`);
    if (i < wavPaths.length - 1) {
      lines.push(`file '${gapPath}'`);
    }
  }
  lines.push(`file '${paddingPath}'`);

  fs.writeFileSync(listPath, lines.join("\n"));
  execSync(
    `ffmpeg -y -f concat -safe 0 -i "${listPath}" -ar 44100 -ac 1 "${outputPath}" 2>/dev/null`
  );

  // 清理临时文件
  [listPath, paddingPath, gapPath].forEach((f) => {
    try { fs.unlinkSync(f); } catch {}
  });
}

// =============================================================
// Main
// =============================================================

function main() {
  const chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
  const subtitles = JSON.parse(fs.readFileSync(subtitlesPath, "utf-8"));
  fs.mkdirSync(outdir, { recursive: true });

  // 按 shot 分组
  const shotMap = new Map();
  for (const chunk of chunks) {
    if (!chunk.file) continue;
    const shotId = chunk.shot_id;
    if (!shotMap.has(shotId)) shotMap.set(shotId, []);
    shotMap.get(shotId).push(chunk);
  }

  const durations = [];

  for (const [shotId, shotChunks] of shotMap) {
    const wavPaths = shotChunks
      .map((c) => path.join(audiodir, c.file))
      .filter((p) => fs.existsSync(p));

    if (wavPaths.length === 0) {
      console.log(`  [SKIP] ${shotId}: no audio files`);
      continue;
    }

    const outputPath = path.join(outdir, `${shotId}.wav`);
    console.log(`  [CONCAT] ${shotId}: ${wavPaths.length} chunks → ${outputPath}`);

    concatWavFiles(wavPaths, outputPath);

    const duration = getAudioDuration(outputPath);
    console.log(`    → ${duration.toFixed(2)}s`);

    durations.push({
      id: shotId,
      duration_s: Math.round(duration * 1000) / 1000,
      file: `${shotId}.wav`,
    });

    // 根据 concat 结构计算每个 chunk 的实际时间偏移，应用到字幕
    // concat 结构: [padding] [chunk0] [gap] [chunk1] [gap] [chunk2] ... [padding]
    if (subtitles[shotId] && subtitles[shotId].chunks) {
      const flatSubs = [];
      let chunkOffset = PADDING_MS / 1000; // 第一个 chunk 从 padding 后开始

      for (let ci = 0; ci < subtitles[shotId].chunks.length; ci++) {
        const chunkEntry = subtitles[shotId].chunks[ci];

        // 找到对应的 chunk 音频时长
        const matchedChunk = shotChunks.find((c) => c.id === chunkEntry.chunk_id);
        const chunkDuration = matchedChunk ? (matchedChunk.duration_s || 0) : 0;

        for (const sub of chunkEntry.subtitles) {
          flatSubs.push({
            id: sub.id,
            text: sub.text,
            start: Math.round((sub.start + chunkOffset) * 1000) / 1000,
            end: Math.round((sub.end + chunkOffset) * 1000) / 1000,
          });
        }

        // 下一个 chunk 的偏移 = 当前偏移 + chunk 时长 + gap
        if (ci < subtitles[shotId].chunks.length - 1) {
          chunkOffset += chunkDuration + CHUNK_GAP_MS / 1000;
        }
      }

      subtitles[shotId] = flatSubs;
    }
  }

  // 写入 durations.json
  const durPath = path.join(outdir, "durations.json");
  fs.writeFileSync(durPath, JSON.stringify(durations, null, 2));

  // 回写更新后的 subtitles
  fs.writeFileSync(subtitlesPath, JSON.stringify(subtitles, null, 2));

  console.log(`\n=== Output ===`);
  console.log(`  Audio: ${outdir}/<shot>.wav`);
  console.log(`  Durations: ${durPath}`);
  console.log(`  Subtitles: ${subtitlesPath} (偏移已更新)`);
}

main();
