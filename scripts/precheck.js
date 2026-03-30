#!/usr/bin/env node
/**
 * Deterministic pre-checks between pipeline stages.
 * Run cheap validation before expensive AI calls.
 *
 * Usage:
 *   node scripts/precheck.js --stage p2 --chunks <chunks.json> --audiodir <dir>
 *   node scripts/precheck.js --stage p3 --chunks <chunks.json> --transcripts <dir>
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const args = process.argv.slice(2);
let stage = "";
let chunksPath = "";
let audiodir = "";
let transcriptsDir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--stage" && args[i + 1]) stage = args[++i];
  else if (args[i] === "--chunks" && args[i + 1]) chunksPath = args[++i];
  else if (args[i] === "--audiodir" && args[i + 1]) audiodir = args[++i];
  else if (args[i] === "--transcripts" && args[i + 1]) transcriptsDir = args[++i];
}

if (!stage || !chunksPath) {
  console.error("Usage: node precheck.js --stage <p2|p3> --chunks <chunks.json> [--audiodir <dir>] [--transcripts <dir>]");
  process.exit(1);
}

const chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
let errors = 0;

function getAudioDuration(filePath) {
  try {
    const out = execSync(
      `ffprobe -v quiet -show_entries format=duration -of csv=p=0 "${filePath}"`,
      { encoding: "utf-8" }
    );
    return parseFloat(out.trim());
  } catch {
    return -1;
  }
}

// ========== Post-P2 checks ==========
if (stage === "p2") {
  console.log("=== Pre-check: Post-P2 (TTS output validation) ===\n");

  const synthDone = chunks.filter(c => c.status === "synth_done");
  for (const chunk of synthDone) {
    const wavPath = path.join(audiodir, `${chunk.id}.wav`);

    // Check 1: file exists
    if (!fs.existsSync(wavPath)) {
      console.error(`  ✗ ${chunk.id}: WAV file missing at ${wavPath}`);
      errors++;
      continue;
    }

    // Check 2: duration > 0 and < 60s
    const dur = getAudioDuration(wavPath);
    if (dur <= 0) {
      console.error(`  ✗ ${chunk.id}: WAV duration is ${dur}s (invalid)`);
      errors++;
    } else if (dur > 60) {
      console.error(`  ✗ ${chunk.id}: WAV duration ${dur.toFixed(1)}s exceeds 60s limit`);
      errors++;
    } else {
      // Check 3: duration is reasonable for text length (rough: 3-8 chars/sec for Chinese)
      const charsPerSec = chunk.char_count / dur;
      if (charsPerSec < 2 || charsPerSec > 12) {
        console.warn(`  ⚠ ${chunk.id}: ${chunk.char_count} chars in ${dur.toFixed(1)}s = ${charsPerSec.toFixed(1)} chars/s (unusual)`);
      } else {
        console.log(`  ✓ ${chunk.id}: ${dur.toFixed(1)}s, ${charsPerSec.toFixed(1)} chars/s`);
      }

      // Check: sample rate and channels
      const formatInfo = execSync(
        `ffprobe -v quiet -show_entries stream=sample_rate,channels -of csv=p=0 "${wavPath}"`,
        { encoding: "utf-8" }
      ).trim();
      const [sampleRate, channels] = formatInfo.split(",").map(Number);
      if (sampleRate !== 44100) {
        console.error(`  ✗ ${chunk.id}: sample rate ${sampleRate} != 44100`);
        errors++;
      } else if (channels !== 1) {
        console.error(`  ✗ ${chunk.id}: channels ${channels} != 1 (mono)`);
        errors++;
      }
    }
  }
}

// ========== Post-P3 checks ==========
if (stage === "p3") {
  console.log("=== Pre-check: Post-P3 (Transcription validation) ===\n");

  const transcribed = chunks.filter(c => c.status === "transcribed");
  for (const chunk of transcribed) {
    const jsonPath = path.join(transcriptsDir, `${chunk.id}.json`);

    // Check 1: file exists
    if (!fs.existsSync(jsonPath)) {
      console.error(`  ✗ ${chunk.id}: transcript JSON missing`);
      errors++;
      continue;
    }

    let transcript;
    try {
      transcript = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
    } catch (e) {
      console.error(`  ✗ ${chunk.id}: invalid JSON — ${e.message}`);
      errors++;
      continue;
    }

    // Check 2: has segments
    if (!transcript.segments || transcript.segments.length === 0) {
      console.error(`  ✗ ${chunk.id}: no segments in transcript`);
      errors++;
      continue;
    }

    // Check 3: timestamps are monotonically increasing
    let lastEnd = -1;
    let monotonic = true;
    for (const seg of transcript.segments) {
      if (seg.start < lastEnd - 0.01) { // 10ms tolerance
        monotonic = false;
        break;
      }
      if (seg.end < seg.start) {
        monotonic = false;
        break;
      }
      lastEnd = seg.end;
    }
    if (!monotonic) {
      console.error(`  ✗ ${chunk.id}: timestamps not monotonically increasing`);
      errors++;
      continue;
    }

    // Check 4: transcribed text length vs original (within 15% tolerance)
    const transcribedText = transcript.full_transcribed_text || "";
    const originalLen = chunk.text.replace(/[^\u4e00-\u9fff\w]/g, "").length; // count meaningful chars
    const transcribedLen = transcribedText.replace(/[^\u4e00-\u9fff\w]/g, "").length;
    const ratio = originalLen > 0 ? transcribedLen / originalLen : 0;

    if (ratio < 0.7 || ratio > 1.3) {
      console.error(`  ✗ ${chunk.id}: char count mismatch — original ${originalLen}, transcribed ${transcribedLen} (ratio ${ratio.toFixed(2)})`);
      errors++;
    } else {
      console.log(`  ✓ ${chunk.id}: ${transcript.segments.length} segments, char ratio ${ratio.toFixed(2)}`);
    }
  }
}

if (errors > 0) {
  console.error(`\n✗ ${errors} error(s) found. Fix before proceeding.`);
  process.exit(1);
} else {
  console.log(`\n✓ All checks passed.`);
}
