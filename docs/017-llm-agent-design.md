# 017 — LLM Agent 介入点设计

> 日期: 2026-04-13 （最近回看: 2026-04-21）
> **状态：🟡 Planned（二期路线，当前未实装）**
>
> 代码侧未发现任何对应实现：无 `server/core/llm_client.py`、无 Ollama 调用封装、无 `p1r/p2r` 预筛 task、无 `/chunks/{cid}/suggestions` API、无 `AgentBanner/SuggestionCard` 前端组件、无相关测试。
>
> 本文保留为决策档案。启动时建议先做 PoC：在 P2v 后追加可插拔的 `p2r_review` task，仅对 score 低于阈值的 chunk 触发 LLM，验证建议质量后再全量接入。

---

## 1. 架构方案

### 1.1 整体定位

Agent 节点与主 pipeline 并行，不阻塞生产流程。

```
主 pipeline（不变）:
  P1 → P2 → P2c → P2v → P5 → P6 → done

并行旁路:
  P1 完成时 → 预筛 → 可疑 chunks → P1r Agent → 建议
  P2v 完成时 → 预筛 → 有差异 chunks → P2r Agent → 建议
```

建议到了随时可看，用户自己决定什么时候处理。Agent 失败/超时不影响主流程。

### 1.2 确定性预筛 + LLM 只审可疑项

**不全量过 LLM。** 用确定性正则预筛，只把可疑 chunk 送 LLM：

```
P1r 预筛:
  正则 [a-zA-Z]{2,} 或 \d+[a-zA-Z] → 含英文/数字混合 → 送 LLM
  纯中文 → 跳过

P2r 预筛:
  original_text vs transcribed_text 差异 > 阈值 → 送 LLM
  char_ratio ≈ 1.0 且无英文 token 丢失 → 跳过
```

20 个 chunk 的 episode，通常只有 3-5 个需要 LLM 审查。

### 1.3 新增 Stage

| Stage | 触发 | 预筛 | 输入 | 输出 |
|-------|------|------|------|------|
| `p1r` | P1 完成后异步 | 含英文/数字的 chunk | chunk.text | suggestions |
| `p2r` | P2v 完成后异步 | 转写有差异的 chunk | original + transcribed | suggestions |

### 1.4 数据流

```
P1r:
  预筛:   re.findall(r"[a-zA-Z]{2,}", chunk.text) → 有匹配才继续
  input:  chunk.text_clean + 匹配到的英文 tokens 列表
  LLM:    "以下英文词要给中文 TTS 朗读，哪些可能发音不准？"
  output: [{ token, issue, suggestion, confidence }]
  存储:   chunk.extra_metadata.suggestions (JSONB)

P2r:
  预筛:   英文 token 在转写中未原样出现 → 有丢失才继续
  input:  original_text + transcribed_text + 丢失的 token 列表
  LLM:    "以下英文词在转写中变成了其他内容，给出修改建议"
  output: [{ token, original, transcribed, suggestion }]
  存储:   chunk.extra_metadata.suggestions (JSONB)
```

### 1.5 存储

suggestions 存 `chunk.extra_metadata` JSONB，不加新表。生命周期短（accept/dismiss 后无用），且和 chunk 1:1 绑定。

---

## 2. 技术选型

### 2.1 Agent 架构：接口 + 可插拔实现

```python
# 接口（Pipeline 唯一依赖）
class ReviewAgent(Protocol):
    async def review(self, ctx: ReviewContext) -> list[Suggestion]: ...

# v1 实现（当前）
class PromptReviewAgent:    # 单次 LLM 调用

# v2 扩展（未来）
class ToolReviewAgent:      # LLM + 工具调用（知识库等）
```

扩展只需加实现 + 改 DI 注入，不改 Pipeline/API/前端。

### 2.2 LLM 选择

**Ollama qwen3.5:9b**（本地）

- 任务简单（给定英文 token 列表 → 判断发音风险），不需要大模型
- 零成本、零网络依赖
- 通过 config 可切换模型

### 2.3 调用方式

httpx 直调 Ollama OpenAI 兼容 API。不加 SDK 依赖。

```python
# server/core/llm_client.py
class OllamaClient:
    async def chat(self, prompt: str, system: str = "") -> str:
        resp = await self._http.post(f"{self.base_url}/v1/chat/completions", json={...})
        return resp.json()["choices"][0]["message"]["content"]
```

### 2.4 配置

```
# .env
LLM_BASE_URL=http://localhost:11434
LLM_MODEL=qwen3.5:9b
LLM_TIMEOUT=30
```

---

## 3. UI 设计

### 3.1 复用原型

基于 `prototype-chunk-pipeline.html` 的 needs_review 交互模式改造：

| 原型设计 | 改为 |
|----------|------|
| L0/L1/L2 自动循环的 retry-row | 单次合成，Agent 并行审查 |
| P2v FAIL 分数 + 诊断文案 | Agent 生成的建议内容 |
| review-mode editor banner | Agent 建议卡片 |
| "重置并重试" 按钮 | [接受] / [忽略] / [手动编辑] |
| `ed-h-tag-l2` (repair-l2) | `ed-h-tag-agent` (agent 建议) |

### 3.2 三个 UI 组件

**AgentBanner（Episode 级）**

P1r 完成后，如有 pending suggestions，在 TtsConfigBar 下方显示：

```
⚠ Agent 发现 2 个 chunk 有发音风险    [查看全部] [全部忽略]
```

全部处理完自动消失。

**StagePipeline 扩展**

P2r 节点（和 p1c/p2c 类似的 gate 样式）：
- 无建议：绿色 ✓
- 有 pending 建议：黄色 ⚠
- Agent 跳过（纯中文）：不显示
- Agent 失败：静默跳过，不显示错误

**SuggestionCard（Chunk 级）**

嵌在 ChunkRow 内，StagePipeline 下方：

```
┌─ 💡 Agent 建议 ────────────────────────────┐
│ "RAG" — 三字母缩写，TTS 可能读错            │
│  建议: 改为 "R A G"                          │
│                        [接受] [忽略]          │
└──────────────────────────────────────────────┘
```

### 3.3 Accept 链路

```
用户点 [接受]
  → 更新 chunk.text_normalized（应用建议）
  → 记录 normalized_history（tag: agent-p1r / agent-p2r）
  → 触发 POST /chunks/{cid}/retry?from_stage=p2&cascade=true
  → P2 用新 text 重新合成 → P2c → P2v → P5
  → SSE 实时更新前端
```

和现有"编辑文本 → Apply → retry"完全相同的链路，触发源从人工编辑变成 Agent 建议。

---

## 4. 实施路径

### Phase 1：验证 prompt

不写 pipeline 代码。用真实数据测 LLM 识别能力。

数据源：
- `test/pronunciation-test/` E2E 产出的真实转写数据
- `test/ab-param-test/output/` AB 测试 9 组转写结果

评估指标：
- 准确率 > 80%（建议中确实有问题的比例）
- 误报率 < 20%（建议了但没问题的比例）
- 误报比漏报更严重（每个误报都需要人工判断）

测试用例：
```
server/tests/tasks/test_llm_review.py
├── test_p1r_detects_english_tokens        — 含英文文本 → 期望识别
├── test_p1r_no_false_positive             — 纯中文 → 期望零建议
├── test_p1r_suggestion_format             — 输出合法 JSON
├── test_p2r_detects_mispronunciation      — (原文, 转写) 对 → 识别偏差
├── test_p2r_no_false_positive_on_match    — 原文≈转写 → 零建议
└── test_p2r_with_real_data                — AB 测试真实数据
```

### Phase 2：后端集成

```
server/core/
├── agent.py                 ← ReviewContext, Suggestion, ReviewAgent Protocol
├── llm_client.py            ← LLMClient Protocol + OllamaClient
└── agents/
    └── prompt_agent.py      ← v1: PromptReviewAgent

server/flows/tasks/
├── p1r_review.py            ← 预筛 + Prefect task
└── p2r_review.py            ← 预筛 + Prefect task
```

新增 API：
- `GET /episodes/{id}/chunks/{cid}/suggestions`
- `POST /episodes/{id}/chunks/{cid}/suggestions/{idx}/accept`
- `POST /episodes/{id}/chunks/{cid}/suggestions/{idx}/dismiss`

### Phase 3：前端

- AgentBanner 组件
- SuggestionCard 组件
- StagePipeline 扩展 p1r/p2r 节点
- normalized_history tag: `agent-p1r` / `agent-p2r`

---

## 5. 关键决策

| 决策 | 结论 | 理由 |
|------|------|------|
| 全量 vs 预筛 | 确定性预筛 + 只审可疑项 | 避免无谓 token 消耗和误报 |
| 串行 vs 并行 | Agent 与主 pipeline 并行 | 不阻塞生产流程 |
| Agent 架构 | 接口 + 可插拔实现 | v1 简单 prompt，v2 可加工具 |
| LLM | Ollama qwen3.5:9b | 任务简单、零成本、本地 |
| 调用方式 | httpx + OpenAI 兼容 | 不加依赖 |
| 存储 | chunk.extra_metadata JSONB | 不加表 |
| UI | 复用原型 needs_review 模式 | 改数据源和操作语义 |
| tts-known-issues.json | 不复用（历史债务） | 格式混乱、无法检索 |
