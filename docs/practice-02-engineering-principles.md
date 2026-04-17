# TTS Harness 工程实践（二）：编程工程化思想

> 项目：tts-agent-harness — 视频脚本转语音+字幕生产工具
> 时间跨度：2026-03-30 ~ 2026-04-14（16 天，239 commits）

---

## 一、确定性优先原则

### 1.1 什么是"确定性优先"

这个项目的核心信条是：**能用确定性规则解决的问题，绝不用概率模型。** 这不是一开始就有的认识，而是从 P4 Claude 校验的失败中学到的。

初始架构（3/30）：

```
P1(确定) → P2(API) → P3(模型) → P4(LLM) → P5(确定) → P6(确定)
```

最终架构（4/14）：

```
P1(确定) → P1c(确定) → P2(API) → P2c(确定) → P2v(模型+评分) → P5(确定) → P6(确定) → P6v(确定)
```

变化的核心逻辑：
- **P3（WhisperX 转写）并入 P2v** — 转写不再是独立阶段，而是验证阶段的输入
- **P4（Claude 校验）被删除** — LLM 做运行时判断不可靠
- **新增 gate check stages（P1c/P2c/P6v）** — 用确定性规则做质量把关
- **P2v 只给评分，不做判断** — 人来决定是否通过

### 1.2 确定性检查的设计

Gate check stages 的设计遵循一个简单原则：**检查那些可以用确定性规则验证的属性，把不能确定性验证的留给人。**

| Stage | 检查内容 | 确定性 |
|-------|---------|--------|
| P1c | chunks 数组非空、每个 chunk 的 text 非空 | 100% |
| P2c | WAV 采样率（44100Hz）、声道数（mono）、时长范围（0.1s-300s） | 100% |
| P6v | 总音频覆盖率、gap/overlap 检查 | 100% |
| P2v | duration 偏差 + silence 比例 → 加权评分 | 评分确定，阈值判断交给人 |

### 1.3 P2v 评分体系的演进

P2v 的评分体系经历了三次迭代：

**V1：5 维评分（4/13 14:12）**

```python
dimensions = [
    "char_ratio",      # 转写字符比率
    "duration_ratio",  # 时长与预期比
    "silence_ratio",   # 静音比例
    "word_count",      # 词数匹配度
    "pronunciation",   # 发音相似度
]
```

**V2：2 维评分（4/13 17:21）**

```python
dimensions = [
    "duration",   # 时长偏差
    "silence",    # 静音比例
]
```

砍掉 char_ratio / word_count / pronunciation 的原因：这三个维度依赖 ASR 转写质量，而 ASR 对中英混合文本的转写本身就不稳定，用一个不稳定的信号去评判另一个不稳定的输出，噪声太大。

**最终方案：** 只保留能从 WAV 文件本身确定性提取的信号（duration、silence），放弃依赖 ASR 转写质量的信号。

### 1.4 Repair Loop 的一日生灭

repair loop 是确定性原则最极端的案例：

```
4/12 12:02  创建 repair module + synth loop（L0/L1 auto-retry）  +822 行
4/13 18:01  移除 L0/L1 repair loop                               -109 行
4/13 18:08  清理 dead repair module                               -536 行
```

设计意图是好的——P2v 评分不达标时自动重试。但 TTS 合成的非确定性意味着：
- 同一段文本重试 3 次，可能得到 3 个质量差不多的结果
- 真正的发音问题（如"Karpathy"读成"卡帕西"）不是重试能解决的，需要人改文本
- 自动重试浪费 API 调用费用，延长用户等待时间

最终结论：**单次合成 + 人工判断 > 自动重试循环**。

---

## 二、类型安全贯穿全链路

### 2.1 从手写 adapter 到零手写类型的四个阶段

这个项目的前后端类型安全体系经历了 4 个阶段，每个阶段都是对上一个阶段痛点的回应。

**阶段 1：手写六边形架构（4/10 09:01）**

```
web/lib/
  adapters/api/
    http-client.ts      # 手写 HTTP 客户端
    episode-store.ts    # 手写 episode CRUD
    chunk-store.ts      # 手写 chunk CRUD
    pipeline-runner.ts  # 手写 pipeline 操作
    observability.ts    # 手写 SSE 客户端
    mappers.ts          # 手写 snake→camel 映射
  ports/
    episode-store.ts    # 接口定义
    chunk-store.ts
    ...
  factory.ts            # 适配器切换层
```

总计 +867 行。问题：手写 mapper 层容易漏字段、类型不同步、维护成本高。

**阶段 2：前端重构对齐（4/10 09:50）**

删除旧 adapters，简化 ports，重写 adapters/api/。净 -2901 行 / +432 行。但核心问题没解决——类型还是手写的。

**阶段 3：openapi-typescript codegen（4/10 10:21）**

关键突破：
1. 后端 Pydantic 模型加 `alias_generator=to_camel`，API 输出 camelCase
2. 从 FastAPI 导出 `openapi.json`
3. 用 `openapi-typescript` 生成 `openapi.d.ts`（953 行）

commit message 写道："This is now the single source of truth for frontend types"

**阶段 4：openapi-fetch 替换手写层（4/10 10:44）**

用 `openapi-fetch`（类型安全的 HTTP 客户端）替换所有手写代码：

```typescript
// 之前：手写 adapter + 手写类型
const episode = await episodeStore.getById(id);

// 之后：自动推导类型
const { data } = await api.GET("/episodes/{episode_id}", {
  params: { path: { episode_id: id } },
});
```

删除约 1000 行手写代码：
- `web/lib/adapters/` 整个目录
- `web/lib/ports/` 整个目录
- `web/lib/factory.ts`
- `web/app/api/` 所有 Next.js Route Handlers

### 2.2 最终的类型安全链路

```
server/core/domain.py (Pydantic + alias_generator=to_camel)
  ↓ FastAPI auto-generates
web/lib/gen/openapi.json
  ↓ openapi-typescript
web/lib/gen/openapi.d.ts (1145 行，自动生成)
  ↓ openapi-fetch
web/lib/api-client.ts (25 行，手写)
  ↓
hooks.ts → components
```

**手写的类型代码：0 行。** 所有前端类型由后端 Pydantic 模型单源驱动。

### 2.3 api-client.ts：25 行解决一切

最终的 API 客户端只有 25 行有效代码：

```typescript
import createClient from "openapi-fetch";
import type { paths } from "./gen/openapi";

export const api = createClient<paths>({
  baseUrl: API_URL,
  headers: API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {},
  credentials: "include",
});
```

从 +867 行手写 adapter 到 25 行 codegen 客户端——这个演进过程本身就是一个工程化的案例。

### 2.4 经验总结

1. **不要一开始就追求完美架构**：手写 adapter 层在项目初期帮助快速跑通了前后端联调，后来再用 codegen 替换是自然的演进
2. **后端 camelCase 是关键决策**：FastAPI 默认 snake_case，加 `alias_generator=to_camel` 后前端不再需要 mapper 层
3. **类型安全的 ROI 随项目规模指数增长**：30 个 endpoint 以下手写还行，30 个以上必须 codegen

---

## 三、分层架构演进

### 3.1 三次架构转型

| 阶段 | 架构 | 触发条件 |
|------|------|----------|
| V1（3/30） | CLI：`run.sh` + `scripts/*.js` + Python P3 | 初始版本，能用就行 |
| V2（4/8） | Web MVP：Next.js + fixture 数据 | 需要 GUI 试听和编辑 |
| V3（4/9-4/10） | 全栈：Next.js + FastAPI + Prefect + PG + MinIO | 需要持久化、并发、状态管理 |

### 3.2 V1→V2：为什么需要 Web

CLI 版本的痛点：
- 听音频需要打开 Finder 找文件
- 修改文本需要编辑 JSON 文件
- 没有状态持久化，中断后需要从头来
- 批量操作不直观

Web MVP 的目标很克制：先用 fixture 数据跑通 UI 原型，验证交互设计可行后再接真实后端。

```
4/8 14:18  L1 业务设计文档
4/8 14:34  Wave 0 — Next.js scaffold + domain types + port interfaces
4/8 14:53  Wave 1 — components + page (fixture mode)
4/8 14:59  Wave 1 — legacy adapters + routes
4/8 15:08  Wave 2 — preview filename + README MVP
4/8 17:34  Post-MVP polish — audio play, state sync
```

从设计到 MVP 可交互：**3 小时**。

### 3.3 V2→V3：为什么重写后端

Web MVP 用 Next.js Route Handler 做"假后端"（读写 JSON 文件），很快就遇到了：
- 没有持久化（刷新丢数据）
- 没有并发控制（多个 TTS 请求打爆 API 限流）
- 没有状态机（episode/chunk 的状态转换没有保障）
- 没有事件通知（前端轮询效率低）

ADR-001 评估了 5 个方案：

| 方案 | 评估 |
|------|------|
| Hono + SQLite | 轻量但缺 workflow 编排 |
| Temporal | 功能强但运维复杂 |
| Dramatiq + Celery | 需要 Redis/RabbitMQ |
| Airflow | 过重，DAG 模型不适合 |
| **Prefect 3 + FastAPI** | **选中：Python 原生、无外部 broker、task 级别 DI** |

选 Prefect 的关键理由：
- WhisperX（P3）是 Python 库，backend 用 Python 可以直接调用
- Prefect 3 不需要额外 broker（自带 server）
- Task 级别的依赖注入和 concurrency limit 原生支持
- 未来可以平滑切换到 Prefect Cloud

### 3.4 为什么选 PostgreSQL + MinIO 而不是 SQLite + 本地文件

```
SQLite + 本地文件 → 单机限制，无法部署到 Fly.io
PostgreSQL + MinIO → 可以用 Fly Postgres + Tigris S3，部署无改动
```

这个决策在 4/13 部署到 Fly.io 时得到验证：只需要把环境变量指向 Fly Postgres 和 Tigris S3 endpoint，代码零修改。

---

## 四、Dev Mode 双轨设计

### 4.1 问题

Prefect 是一个 workflow 编排引擎，完整运行需要：
- Prefect Server（API + UI）
- Prefect Worker（执行 task）
- PostgreSQL（Prefect 元数据）

本地开发每次启动 3 个进程 + Docker，反馈循环太慢。

### 4.2 设计

Dev Mode 的核心思想：**绕过 Prefect 编排，直接在 API 进程内执行 task 函数，但保持 API 接口完全一致。**

```python
# 生产模式
if USE_PREFECT:
    await prefect_flow.submit(episode_id=eid)

# Dev 模式
else:
    asyncio.create_task(_run_dev(eid, session))
```

`_run_dev` 函数直接调用 task 的纯逻辑函数（不经过 Prefect 的 task 装饰器），保持了：
- 相同的 API 端点
- 相同的 SSE 事件推送
- 相同的状态机转换
- 相同的 stage_runs 记录

### 4.3 Dev Mode 容错（4/12 设计文档 016）

Dev Mode 的第一版没有容错——一个 chunk 的 P2 合成失败，整个 episode 就挂了。

改进后的设计：
- **per-chunk 隔离**：每个 chunk 的处理链（P2→P2c→P2v）独立 try/except，单个失败不影响其他
- **P2 重试**：Fish API 偶发超时，自动重试 3 次（backoff 2/4/8s）
- **状态聚合**：Episode 最终状态由 chunk 状态聚合决定
  - 全部 verified → done
  - 存在 failed → failed
  - 存在 pending → partial

```python
async def _run_dev(episode_id, session):
    for chunk in chunks:
        try:
            await p2_synth(chunk)
            await p2c_check(chunk)
            await p2v_verify(chunk)
        except Exception as e:
            chunk.status = "failed"
            emit_event("stage_failed", chunk_id=chunk.id, error=str(e))
            continue  # 不阻断其他 chunk
```

### 4.4 关键决策：retry_chunk 也走 Dev Mode

单 chunk 重试（用户点击 synthesize 按钮）也要支持 Dev Mode：

```python
# 之前（错误）：调用 Prefect flow
await retry_chunk_flow.submit(chunk_id=cid)

# 之后（正确）：直接调用 raw function
await _retry_chunk_dev(chunk_id=cid, session=session)
```

commit `7222940` 的 message 写得很直白："call raw functions, not Prefect flows"

---

## 五、Pipeline 设计

### 5.1 Pipeline 拓扑

```
P1 切分 → P1c 校验 → P2 TTS合成 → P2c WAV校验 → P2v 转写验证 → P5 字幕 → P6 拼接 → P6v 端到端验证
```

设计原则：**每个确定性阶段后面跟一个 gate check**。

```
[确定性]  P1  → [gate] P1c
[非确定] P2  → [gate] P2c → [半确定] P2v
[确定性]  P5  → (无 gate，P5 是确定性的，不需要检查)
[确定性]  P6  → [gate] P6v
```

### 5.2 Gate 的视觉区分

前端的 StagePipeline 组件对 gate stages 有视觉区分——gate stages 用不同的样式渲染，让用户理解"这是自动检查，不是处理步骤"。

commit `e7f8d29`："extend StageName to 9 stages with gate visual distinction"

### 5.3 chunk-level vs episode-level stages

一个重要的设计决策是区分 chunk-level 和 episode-level stages：

```
Chunk-level:  P2 → P2c → P2v → P5  （每个 chunk 独立执行）
Episode-level: P1 → P1c              （切分整个 script）
               P6 → P6v              （拼接所有 chunks）
```

这个区分决定了：
- chunk-level stages 可以单独重试
- episode-level stages 只能全量重跑
- 前端 ChunkRow 只显示 chunk-level stages 的进度

commit `c3d20ad`："chunk pipeline shows only chunk-level stages (P2/P2c/P2v/P5)"

---

## 六、测试分层

### 6.1 三层测试策略

| 层 | 工具 | 测试内容 | 文件数 |
|----|------|---------|--------|
| 纯逻辑单测 | pytest | P1/P5/P6 的纯逻辑函数 | 16 |
| 集成测试 | pytest + dev stack | API 路由 + DB + MinIO 联调 | 7 |
| E2E | Playwright | 浏览器自动化测试完整用户流程 | 2 |

### 6.2 测试的务实原则

**Mock 边界明确：**
- Fish Audio API → mock（不在测试时花钱调用真实 API）
- WhisperX / Groq → mock（测试环境没有 GPU）
- PostgreSQL → 真实（dev stack docker-compose 提供）
- MinIO → 真实（dev stack docker-compose 提供）

```python
# tests/mocks/mock_tts_provider.py — 生成可解析的 WAV 文件
class FakeFish:
    async def synthesize(self, text, **kwargs):
        # 返回一个有效的 44100Hz mono WAV 文件
        return generate_sine_wave(duration=len(text) * 0.05)
```

**测试什么、不测什么：**
- ✅ 测试纯逻辑（P5 字幕时间戳计算、P6 拼接偏移、P2v 评分公式）
- ✅ 测试 API 契约（status code、response schema）
- ✅ 测试状态机转换（pending→synth_done→verified→done）
- ❌ 不测 TTS 合成质量（非确定性）
- ❌ 不测 UI 样式（变化太快，ROI 低）

### 6.3 E2E 测试的分层设计

docs/006-e2e-plan.md 中定义了 4 层测试架构：

```
Playwright → Next.js (3010) → FastAPI (8100) → Postgres + MinIO + Fish(mock) + WhisperX(mock)
```

docs/007-e2e-test-cases.md 定义了 15 个测试用例（TC-01 ~ TC-15），覆盖：
- Episode CRUD（创建、列表、归档）
- Pipeline 执行（合成、校验、验证）
- 单 chunk 操作（重试、编辑文本、take 切换）
- 导出（zip 下载、格式验证）

---

## 七、错误处理架构

### 7.1 设计文档先行

错误处理没有直接开写，而是先产出了 docs/015-error-handling-design.md，评估了四种方案：

| 方案 | 评估 |
|------|------|
| 全局错误拦截 | ✅ 选中：openapi-fetch middleware + global exception handler |
| Loading 状态管理 | 各组件自行管理 loading state |
| Error Boundary | ✅ 选中：React Error Boundary 兜底 |
| Toast 库 | ✅ 选中：sonner（轻量、支持 promise toast） |

### 7.2 两层拦截

```
后端：FastAPI global exception handlers
  ├─ DomainError → 400 + detail message
  ├─ HTTPException → 原样返回
  └─ Exception → 500 + "Internal Server Error"

前端：openapi-fetch middleware
  ├─ response.ok → 透传
  └─ !response.ok → console.error + (由调用方决定是否 toast)
```

### 7.3 Task 层的错误链路

Pipeline task 的错误需要穿透到前端 UI：

```
P2 Fish API 超时
  → httpx.ConnectTimeout
  → task catch → emit stage_failed event (with error detail)
  → SSE push to frontend
  → StageLogDrawer 显示错误信息
```

这个链路调通花了多个 commit：

```
c5b692c  确保 StageRun.error 在 dev mode P2 失败时被持久化
dc4f2d9  错误诊断加入 URL 和 cause chain
e1469c2  从空的 httpx ConnectError 中提取有意义的错误信息
6808cbb  StageLogDrawer 在 StageRun.error 为空时 fallback 到 Event.error
95124b0  去掉重复的错误显示
9a9a04d  确保所有 task 错误路径都 emit stage_failed 事件
```

**教训：错误处理不是一次性的工作，而是一个持续的链路调通过程。** 每一层（httpx → task → event → SSE → UI）都可能丢失或变形错误信息。

---

## 八、核心 Server 文件的职责划分

最终的 server 代码组织体现了清晰的分层：

```
server/
  core/                  # 纯业务逻辑，不依赖框架
    domain.py            # Pydantic 模型（Episode, Chunk, Take, StageRun）
    models.py            # SQLAlchemy ORM 模型
    repositories.py      # 数据访问层
    storage.py           # MinIO 存储抽象
    events.py            # pg_notify 事件发布
    p1_logic.py          # P1 切分纯逻辑
    p5_logic.py          # P5 字幕纯逻辑
    p6_logic.py          # P6 拼接纯逻辑
    p2v_scoring.py       # P2v 评分纯逻辑
    fish_client.py       # Fish Audio API 客户端
    groq_asr_client.py   # Groq Whisper API 客户端
    crypto.py            # API Key 加密
    cleanup.py           # 存储清理
    db.py                # 数据库连接

  flows/tasks/           # Prefect task 定义（编排层）
    p1_chunk.py
    p1c_check.py
    p2_synth.py
    p2c_check.py
    p2v_verify.py
    p5_subtitles.py
    p6_concat.py
    p6v_check.py
    p3_transcribe.py     # 遗留（被 P2v 取代，保留兼容）

  api/routes/            # FastAPI 路由（HTTP 入口）
    episodes.py

  tests/                 # 37 个测试文件
    tasks/               # 纯逻辑单测
    e2e/                 # 集成测试
    api/                 # API 路由测试
    mocks/               # Mock provider
```

关键分层原则：
- `core/` 下的 `*_logic.py` 是**纯函数**，不依赖数据库、不依赖 HTTP、不依赖 Prefect——可以单独 import 和测试
- `flows/tasks/` 负责编排——从 DB 读取数据、调用纯逻辑、写回 DB、发事件
- `api/routes/` 只做 HTTP 转换——解析请求参数、调用 flow/task、序列化响应
