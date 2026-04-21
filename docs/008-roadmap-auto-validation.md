# 自动校验 Pipeline — 实装与决策

> **状态（2026-04-21）**：Phase 1 校验框架 ✅ 已全部实装（P1c/P2c/P2v/P6v）。
> Phase 2-4（自动修复 / 智能调参 / LLM 集成）在 2026-04-11~13 明确**废弃**，改为"单次执行 + 失败交人工 review"。LLM 辅助路线由 [017-llm-agent-design](017-llm-agent-design.md) 承接。

## 目标

Pipeline 每个 stage 完成后自动校验产物正确性，发现问题交人工 review。
原设计中的"自动修复（重试 / 调参 / 换文本）"已判定为过度工程，参见下文"废弃决策"。

## 已实装：校验规则与 Task

| Stage | 校验项 | 实装文件 |
|-------|-------|---------|
| **P1c** | chunk 字数上下限、emoji 过滤、`[break]/[breath]` 等控制标签合法性 | `server/flows/tasks/p1c_check.py` |
| **P2c** | WAV 格式（RIFF/PCM）、采样率、单声道、duration 合理范围 | `server/flows/tasks/p2c_check.py` |
| **P2v** | WhisperX/Groq 转写 + 2D scoring（字符匹配率 + 时长偏差） | `server/flows/tasks/p2v_verify.py` + `server/core/p2v_scoring.py` |
| **P6v** | 端到端：总时长、cue 覆盖率、gap/overlap 检测 | `server/flows/tasks/p6v_check.py` |

校验失败会设置 `chunk.status=needs_review`（或 `failed`），由 UI 上的 ✎（编辑文本重跑 P2）/ ⏱（手动微调 cue）工具人工兜底。

### 原始校验规则表（历史参考）

下表为 2026-04-12 设计时的规则草案。**P3 阶段已在同一轮重构中合并入 P2v**，阶段名随之改动；规则本体大多已落地到对应 task。

<details>
<summary>展开查看原始规则表</summary>

#### P2 (TTS 合成) → P2c
| 检查项 | 规则 |
|---|---|
| WAV header | RIFF 签名 + PCM 格式 |
| Duration | 0.3s < duration < 60s |
| 文件大小 | > 1KB |
| 静音检测 | RMS > 阈值 |

#### P3 (转写) → P2v（现已合并）
| 检查项 | 规则 |
|---|---|
| Word 数量 | > 0 |
| 时间戳单调 | start[i] < start[i+1] |
| 覆盖率 | transcript 总时长 / take duration > 80% |
| 文字匹配 | TTS 源文本 vs 转写文本的相似度（< 60% 标记 needs_review） |

#### P5 (字幕)
| 检查项 | 规则 |
|---|---|
| Cue 数量 | > 0 |
| 时间戳不重叠 | end[i] <= start[i+1] |
| 总时长 | ≤ take duration + 0.1s |

#### P6 (拼接) → P6v
| 检查项 | 规则 |
|---|---|
| Final WAV 时长 | ≈ sum(chunk durations) + padding |
| Final SRT cue 数 | = sum(chunk cue 数) |

</details>

## 废弃决策：自动修复（Phase 2-4）

### 时间线
- `7abf2ff`（2026-04-11）— **remove L0/L1 repair loop**：自动重试机制移除
- `5e391a6`（2026-04-13）— **remove dead repair module**：`RepairConfig` / `RepairAction` 类删除

### 决策理由
1. **Fish S2-Pro 的随机性**使得同文本重试不稳定，"重试同 stage"难以在确定性前提下给出可复现结果
2. **自动调参**（temperature/top_p 微调）效果不显著且引入 Fish API 额外调用成本
3. 人工兜底工具（✎ 编辑文本重跑、⏱ 微调 cue）已经足够高效，错听率 < 5% 的 chunk 字幕自动对齐即可，严重 case 人工 30s 内处理
4. 自动修复会让失败根因被掩盖，不利于暴露 TTS/ASR 真实质量问题

### 当前设计：单次 + 人工 review
```
P1 → P1c → P2 → P2c → P2v → P5 → P6 → P6v
                              │
                              └─ 失败/分数低 → chunk.status=needs_review
                                                UI 提示人工介入
```

不再追求 "pipeline 跑完即交付"。可控性优先于自动化。

## LLM 辅助（原 Phase 4）

原计划的脚本润色、发音诊断、质量打分，已转到独立文档 [017-llm-agent-design](017-llm-agent-design.md) 作为二期路线规划（当前未实装）。
