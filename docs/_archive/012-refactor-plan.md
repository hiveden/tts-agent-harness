# 重构方案 — Pipeline 透明校验与自动修复

## 现状摘要

系统存在两套并行实现：

| 层 | v1（scripts/） | v2（server/） |
|---|---|---|
| 调度 | run.sh + shell 脚本 | Prefect flows |
| 存储 | .work/ JSON 文件 | PostgreSQL + MinIO |
| 状态 | chunks.json status 字段 | Chunk 表 + StageRun 表 |
| 事件 | trace.jsonl | Event 表 + pg_notify + SSE |
| 前端 | v2-preview.html | Next.js + Zustand + SWR |

本次重构基于 **v2 架构**（server/ + web/），不涉及 v1 scripts/。

## 变更范围

### 数据模型（server/core/domain.py + models.py）

**StageName 扩展**：

```python
# 现有
StageName = Literal["p1", "p2", "p3", "p5", "p6"]

# 目标
StageName = Literal["p1", "p1c", "p2", "p2c", "p2v", "p5", "p6", "p6v"]
```

**ChunkStatus 扩展**：

```python
# 现有
ChunkStatus = Literal["pending", "synth_done", "transcribed", "failed"]

# 目标
ChunkStatus = Literal["pending", "synth_done", "verified", "needs_review", "failed"]
```

移除 `transcribed`，替换为 `verified`（P2v 通过即 verified）。

**Chunk 表新增字段**：

```python
# models.py Chunk 表
normalized_history: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
```

注：scripts/p1-chunk.js 已在 chunks.json 中生成 `normalized_history`，但 v2 的 Chunk 表未定义此字段。需要加上。

**StageRun 表新增字段**：

```python
# 现有字段已够用：stage, status, attempt, duration_ms, error, log_uri, stale
# 无需改表结构，P2v 的评估分数存入 Event payload
```

**新增 EventKind**：

```python
# 追加到现有 EventKind
"verify_started"        # P2v attempt 开始
"verify_finished"       # P2v attempt 通过
"verify_failed"         # P2v attempt 失败（含 scores + diagnosis）
"repair_decided"        # Repair 策略决定（含 level + action）
"needs_review"          # 进入人工介入状态
"review_reset"          # 人工修改后重置
```

### 后端 Tasks（server/flows/tasks/）

**新增文件**：

| 文件 | 职责 |
|---|---|
| `p1c_check.py` | P1c 输入校验（chunk 长度/空文本/字符集） |
| `p2c_check.py` | P2c 格式校验（WAV 存在/时长/采样率/声道） |
| `p2v_verify.py` | P2v 内容验证（ASR + 多维评估 + 诊断） |
| `p6v_check.py` | P6v 端到端验证（覆盖率/gap/overlap） |

**修改文件**：

| 文件 | 变更 |
|---|---|
| `p3_transcribe.py` | 不再作为独立 stage 暴露。ASR 能力下沉为 p2v_verify 的内部调用 |
| `p2_synth.py` | Take.params 记录完整参数快照（含 level/attempt 来源） |

**删除/废弃**：

| 文件 | 处理 |
|---|---|
| `p3_transcribe.py` 作为独立 Prefect task | 废弃注册，逻辑保留供 p2v 调用 |

### Repair 调度逻辑（server/flows/）

**新增 `repair.py`**：

```python
async def decide_repair(
    chunk_id: str,
    attempt: int,
    diagnosis: Diagnosis,
    config: RepairConfig,
) -> RepairAction:
    """
    根据当前 attempt、诊断结果和配置，决定下一步修复策略。

    返回:
    - RetryAction(level=0, params=same)        原样重试
    - RetryAction(level=1, params=adjusted)    调参重试
    - RetryAction(level=2, text=rewritten)     改文本重试
    - StopAction(reason="needs_review")        停止，等人工
    """
```

**修改 `run_episode.py`**：

现有流程：
```python
P1 → P2(all chunks) → P3(all chunks) → P5(all chunks) → P6
```

目标流程（per chunk）：
```python
P1 → P1c → for each chunk:
              P2 → P2c → P2v
              while P2v fails and attempt < N:
                repair_decide → P2(new params/text) → P2c → P2v
              if verified → continue
              if needs_review → skip, other chunks continue
           → P5(verified chunks) → P6 → P6v
```

**修改 `retry_chunk.py`**：

现有 `from_stage` 支持 `"p2" | "p3" | "p5"`，改为 `"p2" | "p2v" | "p5"`。
移除对 p3 的引用。

### 前端（web/）

**类型变更（lib/types.ts）**：

```typescript
// StageName
type StageName = "p1" | "p1c" | "p2" | "p2c" | "p2v" | "p5" | "p6" | "p6v";

// STAGE_ORDER
const STAGE_ORDER: readonly StageName[] = [
  "p1", "p1c", "p2", "p2c", "p2v", "p5", "p6", "p6v",
];

// ChunkStatus
type ChunkStatus = "pending" | "synth_done" | "verified" | "needs_review" | "failed";

// 新增
interface VerifyScores {
  durationRatio: number;
  silence: number;
  phoneticDistance: number;
  charRatio: number;
  asrConfidence: number;
  weightedScore: number;
}

interface AttemptRecord {
  attempt: number;
  level: number;
  verdict: "pass" | "fail";
  scores: VerifyScores;
  diagnosis?: Record<string, unknown>;
  params: Record<string, unknown>;
  textUsed: string;
  transcribedText: string;
  durationMs: number;
  timestamp: string;
}
```

**组件变更**：

| 组件 | 变更内容 |
|---|---|
| `stage-info.ts` | 新增 p1c/p2c/p2v/p6v 描述，移除 p3 |
| `StagePipeline.tsx` | STAGE_ORDER 8 个 pill，gate 用方形样式 |
| `EpisodeStageBar.tsx` | CHUNK_STAGES 从 3 扩展到 6（p2/p2c/p2v/p5/p6/p6v） |
| `ChunkRow.tsx` | statusIcon 支持 verified/needs_review。retry 行渲染（下方 P2→P2c→P2v 子 pipeline + Take 信息 + verdict） |
| `ChunkEditor.tsx` | 紧凑行式布局，点击切换编辑态，修改历史直接展示，当前 Take 参数只读行 |
| `StageLogDrawer.tsx` | P2v drawer 展示评估分数条 + 文本对比 |
| `TakeSelector.tsx` | 废弃独立组件，功能合并到 retry 行 |
| `store.ts` | 新增 `attemptHistory` 相关状态 |

**新增组件**：

| 组件 | 职责 |
|---|---|
| `RetryRow.tsx` | 单行 retry 渲染（pipeline pill + take + verdict） |
| `VerifyScoreBar.tsx` | 多维评估分数条 |

### SSE 事件处理

`sse-client.ts` 无需修改，已支持任意 `kind` 字段。
`hooks.ts` 的 `useEpisode` 收到新事件类型时自动 mutate。

### 数据库迁移

```
alembic revision --autogenerate -m "add p2v stages and repair fields"
```

变更：
1. Chunk 表加 `normalized_history` JSONB 列
2. StageRun 表的 `stage` 列允许新值（无约束变更，Text 类型）
3. Chunk 表的 `status` 列允许新值（同上）

### API 端点

**无新增端点**。现有端点已满足：
- `POST /episodes/{id}/run` — mode 扩展支持合成循环
- `POST /episodes/{id}/chunks/{cid}/retry` — from_stage 支持 p2v
- `POST /episodes/{id}/chunks/{cid}/edit` — 复用现有编辑接口
- `POST /episodes/{id}/chunks/{cid}/finalize-take` — 复用现有 take 选择

**修改端点**：
- `GET /episodes/{id}` — 响应中 Chunk 包含 `attemptHistory`（从 Event 表聚合）

## 实施阶段

### Phase 1: Stage 可见化（无功能变更）

目标：把隐藏的检查环节在 UI 上可见，不改执行逻辑。

| 任务 | 改动范围 |
|---|---|
| domain.py 扩展 StageName | 后端 |
| 新建 p1c/p2c/p6v task（逻辑从 precheck 迁移） | 后端 |
| run_episode.py 调用新 task | 后端 |
| types.ts 扩展 StageName/STAGE_ORDER | 前端 |
| stage-info.ts 新增描述 | 前端 |
| StagePipeline 渲染 8 个 pill（gate 方形） | 前端 |
| EpisodeStageBar 扩展 | 前端 |
| 单元测试 | 测试 |

验收：UI 上看到 8 个 stage pill，check gate 有独立状态。

### Phase 2: P2v 合并 + 状态机变更

目标：P3 + check3 合并为 P2v，ChunkStatus 新增 verified。

| 任务 | 改动范围 |
|---|---|
| 新建 p2v_verify.py（ASR + 评估） | 后端 |
| domain.py ChunkStatus 加 verified | 后端 |
| models.py Chunk 表加 normalized_history | 后端 |
| run_episode.py 用 P2v 替代 P3+check3 | 后端 |
| Alembic 迁移 | 后端 |
| types.ts ChunkStatus 更新 | 前端 |
| ChunkRow statusIcon 支持 verified | 前端 |
| StageLogDrawer P2v 展示评估分数 | 前端 |
| 移除 p3 相关 UI（stage-info/pill） | 前端 |

验收：P2v 通过的 chunk 状态为 verified，drawer 展示评估分数。

### Phase 3: 多维评估 + Retry 行

目标：P2v 采用多维评估，UI 展示 retry 行和 take。

| 任务 | 改动范围 |
|---|---|
| p2v_verify.py 加入 5 维评估 | 后端 |
| Event 写入 verify_finished/verify_failed（含 scores） | 后端 |
| 安装 pypinyin 依赖 | 后端 |
| RetryRow 组件 | 前端 |
| VerifyScoreBar 组件 | 前端 |
| ChunkRow 渲染 retry 行 | 前端 |
| TakeSelector 功能合并到 retry 行 | 前端 |

验收：每次 P2v attempt 在 UI 上新增一行，含 pipeline + take + verdict。

### Phase 4: 自动修复循环

目标：P2v 失败后自动 retry（L0/L1），needs_review 状态。

| 任务 | 改动范围 |
|---|---|
| 新建 repair.py（L0/L1 策略） | 后端 |
| run_episode.py 合成循环逻辑 | 后端 |
| domain.py ChunkStatus 加 needs_review | 后端 |
| RepairConfig 配置支持 | 后端 |
| ChunkRow needs_review 高亮 + 编辑器自动展开 | 前端 |
| ChunkEditor 紧凑布局 + 修改历史 + Take 参数 | 前端 |
| needs_review 诊断 banner + 重置重试按钮 | 前端 |
| 测试：mock fixture 驱动的 TC-01~TC-05 | 测试 |

验收：chunk 自动重试 L0/L1，用尽后进入 needs_review，用户可编辑文本并重试。

### Phase 5: L2 智能修复（可选）

目标：自动文本改写。

| 任务 | 改动范围 |
|---|---|
| repair.py L2 策略（品牌名映射表） | 后端 |
| normalized_history 追加 repair-l2 记录 | 后端 |
| ChunkEditor 展示 L2 修改历史 | 前端 |
| 测试 TC-03 | 测试 |

## 不变的部分

| 项目 | 说明 |
|---|---|
| P1 切分逻辑 | 不改 |
| P5 字幕逻辑 | 不改（输入从 transcript.json 改为 P2v 的产出，格式相同） |
| P6 拼接逻辑 | 不改 |
| Episode 级 TTS Config | 不改（chunk 级参数覆盖是 take.params 的属性，不是 chunk 配置） |
| v1 scripts/ | 不改（独立运行，不影响 v2） |
| API 端点签名 | 不改（复用现有端点） |
| SSE 协议 | 不改（新增 event kind，格式不变） |
| MinIO 存储路径 | 不改 |
