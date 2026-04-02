# CLAUDE.md — TTS Agent Harness

多 Agent TTS 语音生产系统。输入脚本 JSON，输出 per-shot WAV + 时间对齐字幕。

## 架构速查

```
P1 切分(JS) → P2 TTS(Fish) → precheck → P3 转写(WhisperX) → precheck → text-diff → P4 校验(Claude) → P5 字幕(JS) → P6 拼接(ffmpeg) → postcheck → V2 预览
```

| 脚本 | 作用 | 确定性 |
|------|------|--------|
| `p1-chunk.js` | 按句切分 + normalize（读 config + patches） | 是 |
| `p2-synth.js` | Fish TTS 并行合成（读 config speed/concurrency） | 否（API） |
| `p3-transcribe.py` | WhisperX 转写，Server 模式常驻 | 否（模型） |
| `text-diff.js` | Levenshtein + 同音字，auto-pass < 10% 差异 | 是 |
| `p4-validate.js` | Claude 校验 + 自动修复循环，最多 3 轮 | 否（LLM） |
| `p5-subtitles.js` | 加权分配 word 时间戳到字幕行 | 是 |
| `p6-concat.js` | ffmpeg 拼接 + padding/gap + 字幕偏移 | 是 |
| `postcheck-p6.js` | 端到端验证：覆盖率/gap/overlap | 是 |
| `precheck.js` | Post-P2（WAV 格式）/ Post-P3（transcript 质量） | 是 |
| `v2-preview.js` | HTML 字幕预览页 | 是 |

## 状态机

```
pending → synth_done → transcribed → [text-diff auto-pass] → validated
                                   → [needs P4] → validated / needs_human
```

## .harness/ 三层分离

```
.harness/
├── config.json                ← 技术参数（P1/P2/P3/P4/P5/P6 读取）
├── rules.md                   ← 业务规则（人写，P4 Claude prompt 注入，harness 只读）
├── normalize-patches.json     ← 自动积累的 normalize 补丁（P1 读，P4 写）
└── tts-known-issues.json      ← 已知 TTS 限制（P4 prompt 注入 + P4 写）
```

## 运行方式

```bash
# 完整运行
bash run.sh <script.json> <episode_id>

# 断点续跑
bash run.sh <script.json> <episode_id> --from p3

# 产物复制到目标项目
bash run.sh <script.json> <episode_id> --output-dir /path/to/public/tts
```

## 环境变量（.env，不进 git）

| 变量 | 必需 | 说明 |
|------|------|------|
| `FISH_TTS_KEY` | 是 | Fish TTS API 密钥 |
| `FISH_TTS_REFERENCE_ID` | 否 | 声音克隆 ID（不设则用默认声音） |
| `FISH_TTS_MODEL` | 否 | 覆盖 config.json 的 p2.model |
| `TTS_SPEED` | 否 | 覆盖 config.json 的 p2.default_speed |
| `CLAUDE_API_URL` | 否 | 覆盖 config.json 的 p4.proxy_url |
| `CLAUDE_MODEL` | 否 | 覆盖 config.json 的 p4.model |

所有参数优先级：环境变量 > `.harness/config.json` > 代码默认值。

使用时 `source .env && bash run.sh ...`。模板见 `example/.env.example`。

## 测试

```bash
bash test/run-unit.sh    # 52 个离线单元测试，~2 秒
bash test.sh --p1-only   # P1 切分测试，无需 API
bash test.sh --no-p4     # P1→P6 跳 Claude，需 FISH_TTS_KEY
bash test.sh             # 全量含 P4
```

## 开发约定

- 改 P1 normalize 规则 → 同步更新 `.harness/rules.md`
- 改任何脚本 → 跑 `bash test/run-unit.sh` 验证
- `.harness/normalize-patches.json` 和 `tts-known-issues.json` 是运行时产物，被 `.gitignore` 排除
- chunks.json 中 `text` 是原文（用于字幕），`text_normalized` 是 TTS 输入（可被 P4 修改）
- `normalized_history` 记录每轮修改（round/value/source/reason），用于审计

## 脚本格式

```json
{
  "title": "Episode Title",
  "segments": [
    { "id": 1, "type": "hook", "text": "要朗读的文本。" },
    { "id": 2, "type": "content", "text": "正文内容。" }
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 数字或字符串。数字会被转为 `shot01`、`shot02`... |
| `type` | 否 | `hook`/`content`/`cta` 等，不影响处理逻辑 |
| `text` | 是 | 要朗读的原始文本。P1 会生成 `text_normalized` 送 TTS |

## 已知限制

- TTS 引擎（Fish TTS）对英文缩写/品牌名的发音不稳定，同样的文本多次合成可能读法不同
- 跨期记忆（normalize-patches / tts-known-issues）记录的是具体替换对，换 TTS 模型或版本后可能失效
- P4 修复能力有限：能修同义词替换，修不了 TTS 引擎固有限制
