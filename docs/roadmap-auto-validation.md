# 自动校验与自动修复 — 后续方向

## 目标

Pipeline 每个 stage 完成后自动校验产物正确性，发现问题自动修复（重试 / 调参 / 换文本），减少人工介入。

## 校验规则

### P2 (TTS 合成)
| 检查项 | 规则 | 修复策略 |
|---|---|---|
| WAV header | RIFF 签名 + PCM 格式 | 重试 P2 |
| Duration | 0.3s < duration < 60s | 如果异常，重新解析 header 或重试 |
| 文件大小 | > 1KB | 重试 P2 |
| 静音检测 | RMS > 阈值 | 重试 P2（可能 Fish API 返回了空白音频） |

### P3 (转写)
| 检查项 | 规则 | 修复策略 |
|---|---|---|
| Word 数量 | > 0 | 重试 P3（WhisperX 可能没检测到语音） |
| 时间戳单调 | start[i] < start[i+1] | 重试 P3 |
| 覆盖率 | transcript 总时长 / take duration > 80% | 警告（可能有静音段） |
| 文字匹配 | TTS 源文本 vs 转写文本的相似度 | 如果 < 60% → P2 发音偏差，建议调参或改文本 |

### P5 (字幕)
| 检查项 | 规则 | 修复策略 |
|---|---|---|
| Cue 数量 | > 0 | 重跑 P5 |
| 时间戳不重叠 | end[i] <= start[i+1] | 重跑 P5 |
| 总时长 | ≤ take duration + 0.1s | 警告 |

### P6 (拼接)
| 检查项 | 规则 | 修复策略 |
|---|---|---|
| Final WAV 时长 | ≈ sum(chunk durations) + padding | 警告 |
| Final SRT cue 数 | = sum(chunk cue 数) | 重跑 P6 |

## 自动修复策略

```
stage 完成
  → 运行校验规则
  → 全部通过 → ok
  → 有失败项:
    → 可自动修复（重试同 stage）:
      → attempt < max_retries → 重试
      → attempt >= max_retries → 标记 failed + 人工介入
    → 需要上游修复（如 P2 发音偏差）:
      → 自动调参重试（temperature ±0.1）
      → 或标记 "建议修改文本" → 人工介入
```

## 实现阶段

### Phase 1: 校验框架
- 每个 stage 一个 `validate_p{N}(result) -> list[ValidationIssue]`
- ValidationIssue: level (error/warning), code, message
- 在 dev runner 和 Prefect task 中调用

### Phase 2: 自动重试
- 校验失败 + level=error → 自动重试同 stage
- max_retries=3，超过标记 failed

### Phase 3: 智能修复
- P2 发音偏差检测（P3 转写 vs TTS 源文本 diff）
- 自动调参（temperature/top_p 微调后重试）
- LLM 辅助文本修正（用 Claude 建议替换发音不准的词）

### Phase 4: LLM 集成
- Script 自动润色（上传前 Claude 优化文本可读性）
- 发音问题自动诊断 + 建议修正
- 质量打分（整 episode 的整体评分）
