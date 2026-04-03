#!/usr/bin/env node
/**
 * P4 — Claude 语义校验 + 自动修复循环
 *
 * 将原始文稿与 WhisperX 转写结果送入 Claude，执行语义级比对。
 * FAIL 的 chunk 自动修改 text_normalized 并重跑 P2→P3→P4，最多 3 轮。
 *
 * 通过 Anthropic API（或 .harness/config.json 配置的 proxy_url）调用 Claude。
 *
 * Usage:
 *   node scripts/p4-validate.js --chunks <chunks.json> --transcripts <dir> --audiodir <dir> --outdir <dir>
 *   node scripts/p4-validate.js --chunks <chunks.json> --transcripts <dir> --audiodir <dir> --outdir <dir> --chunk shot02_chunk01
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execSync } = require("child_process");
const { trace } = require("./trace");

// --- 参数解析 ---
const args = process.argv.slice(2);
let chunksPath = "";
let transcriptsDir = "";
let audiodir = "";
let outdir = "";
let targetChunk = "";
let venvPath = "";
let p3ServerUrl = "";
let tracePath = "";
let harnessDir = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--chunks" && args[i + 1]) chunksPath = args[++i];
  else if (args[i] === "--transcripts" && args[i + 1]) transcriptsDir = args[++i];
  else if (args[i] === "--audiodir" && args[i + 1]) audiodir = args[++i];
  else if (args[i] === "--outdir" && args[i + 1]) outdir = args[++i];
  else if (args[i] === "--chunk" && args[i + 1]) targetChunk = args[++i];
  else if (args[i] === "--venv" && args[i + 1]) venvPath = args[++i];
  else if (args[i] === "--p3-server" && args[i + 1]) p3ServerUrl = args[++i];
  else if (args[i] === "--trace" && args[i + 1]) tracePath = args[++i];
  else if (args[i] === "--harness-dir" && args[i + 1]) harnessDir = args[++i];
}

if (!chunksPath || !transcriptsDir || !audiodir || !outdir) {
  console.error(
    "Usage: node p4-validate.js --chunks <chunks.json> --transcripts <dir> --audiodir <dir> --outdir <dir> [--p3-server <url>] [--harness-dir <dir>]"
  );
  process.exit(1);
}

// --- .harness 目录 ---
const defaultHarnessDir = path.resolve(__dirname, "..");
const resolvedHarnessDir = harnessDir || defaultHarnessDir;

// --- 配置（env 优先 → config.json → 默认值）---
let CLAUDE_PROXY_URL = "https://api.anthropic.com/v1/messages";
let CLAUDE_MODEL = "claude-sonnet-4-20250514";
let MAX_RETRY_ROUNDS = 3;

const configPath = path.join(resolvedHarnessDir, ".harness", "config.json");
try {
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  if (config.p4) {
    MAX_RETRY_ROUNDS = config.p4.max_rounds ?? MAX_RETRY_ROUNDS;
    CLAUDE_MODEL = config.p4.model ?? CLAUDE_MODEL;
    CLAUDE_PROXY_URL = config.p4.proxy_url ?? CLAUDE_PROXY_URL;
  }
} catch {
  // config.json 不存在或格式错误，使用默认值
}
// 环境变量优先覆盖
if (process.env.CLAUDE_API_URL) CLAUDE_PROXY_URL = process.env.CLAUDE_API_URL;
if (process.env.CLAUDE_MODEL) CLAUDE_MODEL = process.env.CLAUDE_MODEL;

// 脚本路径（用于调用 P2/P3 重做）
const SCRIPTS_DIR = path.dirname(__filename);

// =============================================================
// Claude API 调用
// =============================================================

function callClaudeOnce(prompt) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      model: CLAUDE_MODEL,
      max_tokens: 2048,
      messages: [{ role: "user", content: prompt }],
    });

    const url = new URL(CLAUDE_PROXY_URL);
    const httpModule = url.protocol === "https:" ? require("https") : http;
    const req = httpModule.request(
      {
        hostname: url.hostname,
        port: url.port || (url.protocol === "https:" ? 443 : 80),
        path: url.pathname,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": "placeholder",
          "anthropic-version": "2023-06-01",
          "Content-Length": Buffer.byteLength(body),
        },
        timeout: 60000,
      },
      (res) => {
        const statusCode = res.statusCode;
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          try {
            const data = JSON.parse(Buffer.concat(chunks).toString());
            if (statusCode >= 400 && statusCode < 500) {
              // 4xx — client error, not retryable
              reject(Object.assign(new Error(`Claude API ${statusCode}: ${JSON.stringify(data.error || data)}`), { retryable: false }));
              return;
            }
            if (statusCode >= 500) {
              reject(Object.assign(new Error(`Claude API ${statusCode}: ${JSON.stringify(data.error || data)}`), { retryable: true }));
              return;
            }
            if (data.error) {
              reject(Object.assign(new Error(`Claude API error: ${JSON.stringify(data.error)}`), { retryable: false }));
              return;
            }
            const text = data.content?.[0]?.text || "";
            resolve(text);
          } catch (e) {
            reject(Object.assign(new Error(`Failed to parse Claude response: ${e.message}`), { retryable: true }));
          }
        });
      }
    );
    req.on("error", (e) => reject(Object.assign(e, { retryable: true })));
    req.on("timeout", () => { req.destroy(); reject(Object.assign(new Error("Claude API timeout"), { retryable: true })); });
    req.write(body);
    req.end();
  });
}

async function callClaude(prompt) {
  const MAX_ATTEMPTS = 3;
  const BASE_DELAY_MS = 2000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await callClaudeOnce(prompt);
    } catch (e) {
      if (!e.retryable || attempt === MAX_ATTEMPTS) throw e;
      const delay = BASE_DELAY_MS * Math.pow(2, attempt - 1); // 2s, 4s, 8s
      console.log(`    [RETRY] Claude API attempt ${attempt}/${MAX_ATTEMPTS} failed: ${e.message} — retrying in ${delay / 1000}s...`);
      await new Promise((r) => setTimeout(r, delay));
    }
  }
}

// =============================================================
// Prompts
// =============================================================

// --- 加载 rules.md ---
let _rulesContent = null;
function loadRules() {
  if (_rulesContent !== null) return _rulesContent;
  const rulesPath = path.join(resolvedHarnessDir, ".harness", "rules.md");
  try {
    _rulesContent = fs.readFileSync(rulesPath, "utf-8");
  } catch {
    _rulesContent = "";
  }
  return _rulesContent;
}

function buildValidatePrompt(original, normalized, transcribed) {
  const rules = loadRules();
  const rulesSection = rules ? `\n## 业务规则（必须遵守）\n\n${rules}\n` : "";

  return `你是一个中文 TTS 语音质量校验员。
${rulesSection}
## 输入

**原始脚本文本（用于字幕显示）**:
${original}

**TTS 输入文本（经过符号替换的版本）**:
${normalized}

**WhisperX 语音转文字结果（TTS 实际读出的内容）**:
${transcribed}

## 任务

比对「TTS 输入文本」和「转写结果」，识别 TTS 是否正确朗读了内容。

检查以下问题：
1. **错读**：TTS 读错了字（如「-」读成「减」，英文名读错）
2. **漏读**：TTS 输入文本中有但语音中缺失的内容
3. **多读**：语音中出现但 TTS 输入文本没有的内容
4. **语义偏移**：虽然字面接近但含义改变

**不算错误**：
- 同音字替换（的/地/得、做/作）
- 标点差异
- 轻微停顿差异
- 语气词增减（嗯、啊）

## 输出格式

严格输出 JSON，不要有任何其他内容：
{
  "passed": true/false,
  "issues": [
    {
      "type": "misread|missing|extra|semantic_drift",
      "location": "问题出现的位置描述",
      "original": "TTS 输入文本中的原文",
      "transcribed": "转写结果中的对应文本",
      "severity": "high|low",
      "fix": "建议如何修改 TTS 输入文本以避免此问题（仅 high severity 需要）"
    }
  ],
  "summary": "一句话总结校验结果"
}`;
}

function buildFixPrompt(normalized, issues) {
  const issueList = issues
    .filter((i) => i.severity === "high")
    .map((i) => `- [${i.type}] "${i.original}" → "${i.transcribed}" | 建议: ${i.fix}`)
    .join("\n");

  const rules = loadRules();
  const rulesSection = rules ? `\n## 业务规则（必须遵守）\n\n${rules}\n` : "";

  return `你是一个 TTS 文本优化专家。
${rulesSection}
## 当前 TTS 输入文本
${normalized}

## 发现的问题
${issueList}

## 任务

根据上述问题和业务规则修改 TTS 输入文本，使 TTS 能正确朗读。修改原则：
- 只修改有问题的部分，不改其他内容
- 保持语义不变
- 不要把英文人名翻译成中文音译
- 优先调断句/格式，不改原始含义

严格输出 JSON，不要有任何其他内容：
{
  "text_normalized": "修改后的完整 TTS 输入文本",
  "changes": ["修改1的说明", "修改2的说明"]
}`;
}

// =============================================================
// 重做单个 chunk 的 P2→P3
// =============================================================

function resynth(chunkId) {
  console.log(`      [RE-SYNTH] ${chunkId}...`);
  const traceArg = tracePath ? ` --trace "${tracePath}"` : "";
  try {
    execSync(
      `node "${path.join(SCRIPTS_DIR, "p2-synth.js")}" --chunks "${chunksPath}" --outdir "${audiodir}" --chunk "${chunkId}"${traceArg}`,
      { stdio: "pipe", encoding: "utf-8" }
    );
  } catch (e) {
    throw new Error(`P2 re-synth failed: ${e.stderr || e.message}`);
  }
}

async function retranscribe(chunkId) {
  console.log(`      [RE-TRANSCRIBE] ${chunkId}...`);

  // 读取 chunk 信息
  const chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
  const chunk = chunks.find((c) => c.id === chunkId);
  if (!chunk) throw new Error(`Chunk ${chunkId} not found`);

  if (p3ServerUrl) {
    // HTTP 模式 — 调用 P3 server，无需重新加载模型
    const body = JSON.stringify({
      audio_path: path.resolve(path.join(audiodir, `${chunkId}.wav`)),
      chunk_id: chunkId,
      shot_id: chunk.shot_id || "",
      text: chunk.text,
      text_normalized: chunk.text_normalized,
      outdir: path.resolve(transcriptsDir),
    });

    const url = new URL(`${p3ServerUrl}/transcribe`);
    const result = await new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: url.hostname,
          port: url.port,
          path: url.pathname,
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(body),
          },
          timeout: 120000,
        },
        (res) => {
          const chunks = [];
          res.on("data", (c) => chunks.push(c));
          res.on("end", () => {
            try {
              const data = JSON.parse(Buffer.concat(chunks).toString());
              if (data.error) reject(new Error(`P3 server error: ${data.error}`));
              else resolve(data);
            } catch (e) {
              reject(new Error(`Failed to parse P3 response: ${e.message}`));
            }
          });
        }
      );
      req.on("error", reject);
      req.on("timeout", () => { req.destroy(); reject(new Error("P3 server timeout")); });
      req.write(body);
      req.end();
    });

    // 更新 chunk status
    chunk.status = "transcribed";
    fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));
    console.log(`      转写: ${result.full_transcribed_text.slice(0, 50)}...`);
  } else {
    // Fallback — 启动 Python 进程（慢，但不需要 server）
    const pipelineDir = path.resolve(SCRIPTS_DIR, "..");
    const venv = venvPath || path.join(pipelineDir, ".venv", "bin", "python");

    try {
      execSync(
        `"${venv}" "${path.join(SCRIPTS_DIR, "p3-transcribe.py")}" --chunks "${chunksPath}" --audiodir "${audiodir}" --outdir "${transcriptsDir}" --chunk "${chunkId}"`,
        { stdio: "pipe", encoding: "utf-8" }
      );
    } catch (e) {
      throw new Error(`P3 re-transcribe failed: ${e.stderr || e.message}`);
    }
  }
}

// =============================================================
// 解析 LLM JSON 响应
// =============================================================


function parseJSON(text) {
  try {
    return JSON.parse(text);
  } catch {
    // 尝试从 markdown code block 提取
    const match = text.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (match) return JSON.parse(match[1]);
    // 尝试提取裸 JSON
    const match2 = text.match(/\{[\s\S]*\}/);
    if (match2) return JSON.parse(match2[0]);
    throw new Error("Cannot parse JSON from LLM response");
  }
}

// =============================================================
// Main
// =============================================================

async function main() {
  let chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
  fs.mkdirSync(outdir, { recursive: true });

  let toProcess;
  if (targetChunk) {
    toProcess = chunks.filter((c) => c.id === targetChunk);
  } else {
    toProcess = chunks.filter(
      (c) => c.status === "transcribed" || c.status === "validate_failed"
    );
  }

  if (toProcess.length === 0) {
    console.log("No chunks to validate");
    return;
  }

  console.log(`=== P4: Validating ${toProcess.length} chunk(s) with Claude ===\n`);

  let passCount = 0;
  let failCount = 0;
  const needsHuman = [];

  for (const chunkRef of toProcess) {
    // 重新读取最新状态（可能被重试循环更新）
    chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
    const chunk = chunks.find((c) => c.id === chunkRef.id);
    if (!chunk) continue;

    let passed = false;
    const previousNormalized = []; // Track text_normalized across rounds for oscillation detection

    for (let round = 1; round <= MAX_RETRY_ROUNDS; round++) {
      const transcriptPath = path.join(transcriptsDir, `${chunk.id}.json`);
      if (!fs.existsSync(transcriptPath)) {
        console.log(`  [SKIP] ${chunk.id}: transcript not found`);
        break;
      }

      const transcript = JSON.parse(fs.readFileSync(transcriptPath, "utf-8"));

      console.log(
        `  [VALIDATE] ${chunk.id} (round ${round}/${MAX_RETRY_ROUNDS})...`
      );

      try {
        // Step 1: 校验
        const validateResponse = await callClaude(
          buildValidatePrompt(
            chunk.text,
            chunk.text_normalized,
            transcript.full_transcribed_text
          )
        );
        const result = parseJSON(validateResponse);

        // 写入校验结果
        const outPath = path.join(outdir, `${chunk.id}_round${round}.json`);
        fs.writeFileSync(
          outPath,
          JSON.stringify(
            {
              chunk_id: chunk.id,
              round,
              original: chunk.text,
              normalized: chunk.text_normalized,
              transcribed: transcript.full_transcribed_text,
              ...result,
            },
            null,
            2
          )
        );

        if (result.passed) {
          console.log(`    ✓ PASS — ${result.summary || "no issues"}`);
          chunk.status = "validated";
          chunk.validate_round = round;
          fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));

          passCount++;
          passed = true;
          break;
        }

        // FAIL — 检查是否有 high severity
        const highIssues = (result.issues || []).filter(
          (i) => i.severity === "high"
        );
        const lowIssues = (result.issues || []).filter(
          (i) => i.severity === "low"
        );

        console.log(
          `    ✗ FAIL — ${highIssues.length} high, ${lowIssues.length} low`
        );
        for (const issue of highIssues) {
          console.log(
            `      [${issue.type}] "${issue.original}" → "${issue.transcribed}"`
          );
        }

        // 只有 low severity → 放行
        if (highIssues.length === 0) {
          console.log(`    → low severity only, auto-passing`);
          chunk.status = "validated";
          chunk.validate_round = round;
          chunk.low_issues = lowIssues;
          fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));
          passCount++;
          passed = true;
          break;
        }

        // high severity + 还有重试机会 → 自动修复
        if (round < MAX_RETRY_ROUNDS) {
          console.log(`    → Auto-fixing text_normalized...`);

          // Step 2: 让 Claude 修改 text_normalized
          const fixResponse = await callClaude(
            buildFixPrompt(chunk.text_normalized, highIssues)
          );
          const fix = parseJSON(fixResponse);

          const oldNormalized = chunk.text_normalized;

          // Oscillation detection: check if the fix reverts to any previous round's value
          if (previousNormalized.includes(fix.text_normalized)) {
            console.log(`    → oscillation detected — new text_normalized matches a previous round, terminating`);
            chunk.status = "needs_human";
            chunk.oscillation_detected = true;
            chunk.previous_normalized = previousNormalized;
            fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));
            break;
          }

          previousNormalized.push(oldNormalized);
          if (!chunk.normalized_history) chunk.normalized_history = [];
          chunk.normalized_history.push({
            round: round,
            value: fix.text_normalized,
            source: "claude",
            reason: (fix.changes || []).join("; "),
            ts: new Date().toISOString(),
          });
          chunk.text_normalized = fix.text_normalized;
          chunk.previous_normalized = previousNormalized;
          chunk.status = "pending"; // 触发 P2 重做

          console.log(`    → 修改: ${(fix.changes || []).join("; ")}`);
          console.log(
            `      旧: ${oldNormalized.slice(0, 60)}...`
          );
          console.log(
            `      新: ${chunk.text_normalized.slice(0, 60)}...`
          );

          fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));

          // Step 3: 重跑 P2 → P3
          resynth(chunk.id);
          await retranscribe(chunk.id);

          // 重新读取更新后的 chunks
          chunks = JSON.parse(fs.readFileSync(chunksPath, "utf-8"));
          const updatedChunk = chunks.find((c) => c.id === chunk.id);
          if (updatedChunk) Object.assign(chunk, updatedChunk);
        }
      } catch (e) {
        console.error(`    [ERROR] ${chunk.id}: ${e.message}`);
        break;
      }
    }

    if (!passed) {
      chunk.status = "needs_human";
      fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));
      needsHuman.push(chunk);
      failCount++;
    }
  }

  // 最终写入
  fs.writeFileSync(chunksPath, JSON.stringify(chunks, null, 2));

  console.log(
    `\n=== Done: ${passCount} passed, ${failCount} needs human ===`
  );

  if (needsHuman.length > 0) {
    console.log(`\n--- 需要人工介入的 chunk ---`);
    for (const c of needsHuman) {
      console.log(`  ${c.id}: 音频 → ${path.join(audiodir, c.file || "N/A")}`);
      const lastResult = fs
        .readdirSync(outdir)
        .filter((f) => f.startsWith(c.id) && f.endsWith(".json"))
        .sort()
        .pop();
      if (lastResult) {
        const r = JSON.parse(
          fs.readFileSync(path.join(outdir, lastResult), "utf-8")
        );
        console.log(`    最后校验: ${r.summary || "见详情"}`);
      }
    }
    console.log(
      "\n手动修改 chunks.json 中的 text_normalized 后重跑："
    );
    console.log(
      "  node scripts/p4-validate.js --chunk <id> --chunks ... --transcripts ... --audiodir ... --outdir ..."
    );
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
