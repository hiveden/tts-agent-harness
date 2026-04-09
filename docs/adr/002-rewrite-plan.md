# 002 — Agent Teams 重写实施计划

| | |
|---|---|
| **状态** | Proposed |
| **日期** | 2026-04-09 |
| **依赖** | [`001-server-stack.md`](./001-server-stack.md)（技术选型已锁定） |
| **目标** | 用多 Agent 并行重写整个服务端，从绿地（greenfield）建起 |

---

## 0. 指导原则

这次重写**不是迁移**，是**绿地重建**。前提：

1. **当前实现是负债，不是资产**。不读旧代码、不参考旧实现、不做"对照迁移"。任何一行新代码都从需求出发，不从旧文件出发。
2. **多 Agent 并行**是一等公民。能并行的 wave 内部全部并行；只有 wave 之间是依赖串行。
3. **接口先行**。每个 wave 开工前先冻结契约（OpenAPI / SQL DDL / Pydantic schemas），下游 agent 可以拿契约打 mock 先开工。
4. **每个 agent 任务独立可回退**。每个 agent 一个 git 工作树（worktree）或独立分支，主干只在 wave 末尾合并。
5. **过程透明度 > 速度**。所有 agent 产出 markdown 形式的工作日志（决策、放弃的方案、卡点），方便 review 和学习多 Agent 协作模式。

---

## 1. Team Roster（角色定义）

每个 agent 是一个 Claude Code subagent（用 `Agent` 工具 spawn），有明确的输入契约、输出产物、验收标准。

| Agent ID | 角色 | 输入契约 | 输出产物 | 验收 |
|---|---|---|---|---|
| **A0-Architect** | 总架构师（人 + Claude 协作） | ADR-001 | 冻结的 SQL DDL、OpenAPI 草稿、MinIO 路径规范、Prefect deployment 清单 | 文档评审通过 |
| **A1-Infra** | 基础设施 | A0 产物 | `docker/docker-compose.dev.yml`、`server/migrations/` (alembic init + V001 schema)、`make dev` 入口 | `docker-compose up` 全绿；alembic upgrade head 通过 |
| **A2-Domain** | 核心域模型 | SQL DDL + Pydantic schemas 契约 | `server/core/{models,repositories,domain,storage,events}.py` + 单测 | repo CRUD 单测 100% 通过；events INSERT 触发 NOTIFY |
| **A3-WhisperX** | P3 转写服务 | OpenAPI（whisperx-svc 部分） | `whisperx-svc/server.py`、Dockerfile、health check | 容器起得来，POST 一段音频拿到 transcript |
| **A4-Task-P1** | P1 切分 task | Pydantic schema (ChunkInput/Output) | `server/flows/tasks/p1_chunk.py` + 单测 | 给定 script 能切出 chunks，写入 DB |
| **A5-Task-P2** | P2 Fish TTS task | 同上 + Fish API client wrapper | `server/flows/tasks/p2_synth.py` + 单测（Fish API mock） | 单测覆盖正常 / 429 / 超时 / 重试 |
| **A6-Task-P5** | P5 字幕 task | 同上 | `server/flows/tasks/p5_subtitles.py` + 单测 | 给定 transcript 能算出字幕时间戳 |
| **A7-Task-P6** | P6 拼接 task | 同上 | `server/flows/tasks/p6_concat.py` + 单测（ffmpeg 集成） | 给定多个 WAV 能拼接 + 字幕偏移 |
| **A8-Flow** | flow 编排 | A4-A7 完成 + Prefect 部署文档 | `server/flows/{run_episode,retry_chunk}.py` + deployment 注册脚本 | 端到端：触发 flow 跑出完整产物 |
| **A9-API** | FastAPI routes | OpenAPI + A2 repositories | `server/api/{routes,sse,deps,main}.py` | OpenAPI 自动生成；所有 routes 集成测试通过 |
| **A10-Frontend** | 前端 adapter | OpenAPI 生成的 TS 类型 | `web/lib/adapters/api/*` + `web/lib/factory.ts` 切换 | UI 跑通新后端，零 component 改动 |
| **A11-Integration** | 端到端集成测试 | 全部 wave 完成 | `server/tests/e2e/` + testcontainers 配置 | testcontainers 起完整栈，一条 e2e 通过 |
| **A12-Prod** | 生产化 | 全部完成 | `Dockerfile.prod` 多阶段、`docker-compose.prod.yml`、监控埋点、备份脚本 | 部署到 staging 环境烟雾测试通过 |

> **A0** 是协调角色，由人 + Claude 主会话扮演，不 spawn subagent。其余 A1-A12 都是 subagent。

---

## 2. Wave 划分与并行图

```
W0 ─── A0 (架构冻结)
        │
        ▼
W1 ─── A1 (基础设施) ──────────────────┐
                                       │
W2 ─── A2 (核心域) ── A3 (WhisperX) ──┤   ← 两个 agent 并行
                                       │
W3 ─── A4 (P1) ── A5 (P2) ── A6 (P5) ── A7 (P7)   ← 4 个 agent 并行
                                       │
W4 ─── A8 (Flow 编排) ── A9 (API)  ────┤   ← 2 个 agent 并行(共享 A2 产物)
                                       │
W5 ─── A10 (前端 adapter) ── A11 (e2e) ┤   ← 2 个 agent 并行
                                       │
W6 ─── A12 (生产化)
```

依赖说明：
- **W2 不依赖 W1 完成**：A2 用 SQLite in-memory 起步开发，A1 起好 Postgres 后切过来
- **W3 强依赖 W2**：所有 task 要 import `core.repositories` 和 `core.storage`
- **W3 内部完全并行**：每个 task agent 拿同一份 Pydantic schema 各干各的，互不依赖
- **W4 的 A9 不依赖 A8**：只要 A2 完成，FastAPI routes 就可以独立开发；触发 flow 部分用 mock，等 A8 完成后切真
- **W5 的 A11 在 A10 之前可以先动**：用 OpenAPI mock server 跑 e2e

---

## 3. 关键契约（W0 必须冻结）

这一节是所有并行 agent 的同步点。**任何一项契约修改都要人工广播给所有受影响的 agent**。

### 3.1 SQL DDL

冻结在 `server/migrations/versions/V001_initial.py`。schema 见 ADR §5.1。修改流程：写新 migration，不改老 migration。

### 3.2 Pydantic 领域 schema

`server/core/domain.py` —— 这是**前后端共享类型的唯一来源**：

```python
# 必须在 W0 冻结的核心类型
class ChunkInput(BaseModel):
    id: str
    episode_id: str
    text: str
    text_normalized: str
    metadata: dict

class P2Result(BaseModel):
    chunk_id: str
    take_id: str
    audio_uri: str        # s3://...
    duration_s: float

class P3Result(BaseModel):
    chunk_id: str
    transcript_uri: str   # s3://.../transcript.json
    word_count: int

class P5Result(BaseModel):
    chunk_id: str
    subtitle_uri: str     # s3://.../subtitle.srt

class StageEvent(BaseModel):
    episode_id: str
    chunk_id: str | None
    stage: Literal["p1","p2","p3","p5","p6"]
    kind: Literal["started","finished","failed","retry"]
    payload: dict
```

后续 agent **不允许擅自添加业务字段**，要加先回 A0 review。

### 3.3 MinIO 路径规范

```
tts-harness/                      # bucket
├── episodes/{ep_id}/
│   ├── script.json                          # 上传的原始脚本
│   ├── chunks/{cid}/
│   │   ├── takes/{take_id}.wav              # 每个 take 的音频
│   │   ├── transcript.json                  # P3 输出
│   │   └── subtitle.srt                     # P5 输出
│   ├── final/
│   │   ├── episode.wav                      # P6 拼接产物
│   │   └── episode.srt                      # P6 拼接字幕
│   └── logs/{cid}/{stage}.log               # 各 stage 日志
```

### 3.4 OpenAPI 路由清单

W0 必须列全（路径 + 方法 + 请求/响应类型），不需要写实现：

```
GET    /episodes
POST   /episodes
GET    /episodes/{id}
DELETE /episodes/{id}
POST   /episodes/{id}/run
POST   /episodes/{id}/chunks/{cid}/edit
POST   /episodes/{id}/chunks/{cid}/retry
POST   /episodes/{id}/chunks/{cid}/finalize-take
GET    /episodes/{id}/stream         (SSE)
GET    /healthz
```

### 3.5 Prefect Deployment 清单

| Deployment | Flow | 触发方 |
|---|---|---|
| `run-episode` | `run_episode_flow(ep_id)` | FastAPI POST /episodes/{id}/run |
| `retry-chunk-stage` | `retry_chunk_stage_flow(ep_id, cid, from_stage, cascade)` | FastAPI POST /episodes/{id}/chunks/{cid}/retry |
| `finalize-take` | `finalize_take_flow(ep_id, cid, take_id)` | FastAPI POST /episodes/{id}/chunks/{cid}/finalize-take |

---

## 4. 每个 Agent 的 Spawn Prompt 模板

下面给每个 agent 一个**可直接 copy 进 `Agent` 工具 prompt 字段**的模板。每个模板包含：上下文、输入契约、产物清单、验收标准、禁止事项。

### 4.1 A1-Infra

```
你是 A1-Infra agent。任务：建立 docker-compose dev 环境与 Postgres schema。

上下文:
- 阅读 docs/adr/001-server-stack.md §3 (架构图) 和 §5.1 (DDL)
- 阅读 docs/adr/002-rewrite-plan.md §3.1 (SQL DDL)、§3.3 (MinIO 路径)

输入契约:
- ADR §5.1 的完整 SQL DDL
- 容器清单见 ADR §3.2

产出:
1. docker/docker-compose.dev.yml — 包含 postgres / minio / prefect-server / mailhog(可选)
2. server/migrations/ — alembic 初始化 + V001_initial.py 落地全部业务表
3. server/core/db.py — SQLAlchemy engine + session factory(只暴露,不实现 repository)
4. Makefile 入口: make dev / make migrate / make psql / make minio-console
5. 一份 README.md 写明启动顺序

验收:
- `make dev` 起齐全部容器,docker ps 看到全绿
- `make migrate` 能 upgrade head 成功
- 在 MinIO console (localhost:9001) 能看到自动创建的 tts-harness bucket
- Prefect UI (localhost:4200) 可访问

禁止:
- 不写任何业务逻辑
- 不实现 repository / models 字段定义之外的代码
- 不引入除 ADR 列出的依赖之外的任何包

完成后产出 worklog: docs/worklogs/A1-infra.md(决策/卡点/未决问题)
```

### 4.2 A2-Domain

```
你是 A2-Domain agent。任务:实现核心领域模型、repositories、storage wrapper、events 通知。

依赖:
- A1 已完成 alembic schema (你 import 它的 db.py)
- 如果 A1 未完成,用 SQLite in-memory 起步,用 SQLAlchemy 自动建表

产出:
1. server/core/models.py — SQLAlchemy ORM 模型(对应 V001_initial.py)
2. server/core/domain.py — 全部 Pydantic schemas(见 002-rewrite-plan.md §3.2)
3. server/core/repositories.py — EpisodeRepo / ChunkRepo / TakeRepo / StageRunRepo / EventRepo
4. server/core/storage.py — MinIO client wrapper(upload_file / get_url / delete)
5. server/core/events.py — 写 events 表 + pg_notify('episode_events', ...)
6. server/tests/test_repositories.py — CRUD + edge case 单测
7. server/tests/test_events.py — 验证 NOTIFY 能被 LISTEN 收到

验收:
- pytest server/tests/ 100% 通过
- repository 必须支持事务上下文管理
- storage 必须 mockable(用 moto 或 minio testcontainer)

禁止:
- 不写 FastAPI 代码
- 不写 Prefect 代码
- 不直接给出 SQL 字符串,全部走 SQLAlchemy

完成后产出 worklog: docs/worklogs/A2-domain.md
```

### 4.3 A3-WhisperX

```
你是 A3-WhisperX agent。任务:把 WhisperX 包装成独立 HTTP 服务。

输入契约:
- 输入: 一个音频文件(WAV/MP3) + 语言代码
- 输出: 带 word-level timestamp 的 JSON

产出:
1. whisperx-svc/server.py — FastAPI 单文件服务,模型常驻进程内,启动时加载一次
2. whisperx-svc/Dockerfile — 含 ffmpeg + WhisperX 依赖,模型缓存挂载到 /models
3. whisperx-svc/pyproject.toml
4. POST /transcribe — 上传音频 → 返回 transcript JSON
5. GET /healthz — 模型是否 loaded
6. README 写明如何切换 CPU/GPU 模式

验收:
- 容器 cold start <60s(模型加载)
- 第二次 POST 响应时间是秒级(无重新加载)
- POST 一段 30s 中文音频能拿到正确 transcript
- 健康检查通过

禁止:
- 不引入数据库
- 不引入对象存储(音频走 multipart 上传 / 返回 JSON)
- 不写业务逻辑(WhisperX 只负责转写)

完成后产出 worklog: docs/worklogs/A3-whisperx.md
```

### 4.4 A4-A7 Pipeline Tasks(并行)

每个 task agent 用同一个模板,只换名字:

```
你是 A{N}-Task-{P} agent。任务:实现 {P} 阶段的 Prefect task。

依赖:
- A2 已完成 core.domain / core.repositories / core.storage(可 import)
- 如果 A2 未完成,用 in-memory mock 起步

输入契约:
- 输入: {上一阶段的 Pydantic Result type}
- 输出: {本阶段的 Pydantic Result type}
- 必须从 MinIO 读输入,产物写回 MinIO,只在 DB 写 metadata

产出:
1. server/flows/tasks/{p}_xxx.py — @task 装饰的纯函数
2. server/tests/tasks/test_{p}.py — 单测覆盖正常 / 异常 / retry 场景
3. {如适用} server/core/{p}_logic.py — 算法逻辑(纯函数,可被 task 包装)

验收:
- task 必须是确定性的(同输入 → 同输出)
- 必须支持 dry-run 模式(不写 DB / 不写 MinIO)
- 失败时抛 prefect 能捕获的 exception,不吞错
- {P2 specific} 必须带 tags=["fish-api"] 限流标签
- {P3 specific} HTTP 调用 whisperx-svc:7860,不直接 import WhisperX

禁止:
- 不写 flow 编排代码(那是 A8 的事)
- 不直接调用其他 task
- 不假设上下文有 prefect runtime(单测必须能跑)

完成后产出 worklog: docs/worklogs/A{N}-{p}.md
```

任务的具体输入/输出类型见 §3.2。每个 task agent 只负责一个 stage,互不依赖,可同时 spawn。

### 4.5 A8-Flow

```
你是 A8-Flow agent。任务:把 A4-A7 完成的 task 编排成 Prefect flow。

依赖:
- A4/A5/A6/A7 必须全部完成 task 单测

产出:
1. server/flows/run_episode.py — 主 flow,串起 P1 → P2.map → P3.map → P5.map → P6
2. server/flows/retry_chunk.py — mini flow,单 chunk 局部重跑
3. server/flows/finalize_take.py — mini flow,take 选定后跑下游
4. server/flows/deploy.py — Prefect deployment 注册脚本
5. server/flows/concurrency.py — 注册 fish-api concurrency limit
6. server/tests/flows/test_run_episode.py — 端到端集成测试(用 testcontainer)

验收:
- `python -m server.flows.deploy` 能注册全部 deployment 到 prefect-server
- `prefect deployment run run-episode/{ep_id}` 能跑通完整流程
- Fish API 限流在 Prefect UI 上可见
- mini flow 不影响主 flow 的 in-flight run

禁止:
- 不修改 task 内部逻辑(有 bug 让 task agent 改)
- 不引入新的状态(状态全在 A2 的 repository)

完成后产出 worklog: docs/worklogs/A8-flow.md
```

### 4.6 A9-API

```
你是 A9-API agent。任务:实现 FastAPI 应用。

依赖:
- A2 完成 (core.repositories / core.events)
- A8 部分完成 (能 import deployment 名字,但不必跑通)

产出:
1. server/api/main.py — FastAPI app 入口
2. server/api/routes/episodes.py — 全部 episode 相关 routes
3. server/api/routes/health.py — /healthz
4. server/api/sse.py — SSE endpoint + asyncpg LISTEN/NOTIFY
5. server/api/deps.py — DI(get_db / get_storage / get_prefect_client)
6. server/api/auth.py — shared token 鉴权(如果 A0 决定用)
7. server/tests/api/test_routes.py — httpx async client 集成测试

验收:
- OpenAPI schema 自动生成 (/docs 可访问)
- 全部 routes 集成测试通过
- SSE endpoint 能在 NOTIFY 后 100ms 内推送
- 触发 flow 部分:用 prefect_client.create_flow_run_from_deployment

禁止:
- 不写业务逻辑(全部走 repository)
- 不直接操作 SQL
- 不在 route 里 import flow 模块(只用 prefect_client)

完成后产出 worklog: docs/worklogs/A9-api.md
```

### 4.7 A10-Frontend

```
你是 A10-Frontend agent。任务:实现前端 HTTP adapter,对接 FastAPI。

依赖:
- A9 完成,OpenAPI schema 可用

产出:
1. web/lib/adapters/api/ — HTTP client 实现 ports/* 接口
   - episode-store.ts (实现 EpisodeStore port)
   - chunk-store.ts (实现 ChunkStore port)
   - pipeline-runner.ts (实现 PipelineRunner port)
   - observability.ts (实现 PipelineSource / ProgressSource / LogTailer)
2. web/lib/api-client.ts — fetch wrapper + error handling
3. web/lib/sse-client.ts — EventSource wrapper,把 SSE event 转成 React state
4. web/lib/factory.ts — 切换到 api adapter
5. web/lib/__generated__/openapi-types.ts — 用 openapi-typescript 生成
6. scripts/gen-openapi-types.sh — 生成脚本(CI 用)

验收:
- pnpm dev 起前端,选 episode → 触发 run → 实时看到 stage 进度
- 完全不修改 web/components/*.tsx
- TypeScript strict mode 无 error
- 跑前端单测(vitest)无 regression

禁止:
- 不修改任何 component
- 不修改 web/lib/types.ts(它要从 OpenAPI 生成)
- 不引入 swr 之外的状态库

完成后产出 worklog: docs/worklogs/A10-frontend.md
```

### 4.8 A11-Integration

```
你是 A11-Integration agent。任务:端到端集成测试。

依赖:
- A1-A10 全部完成

产出:
1. server/tests/e2e/conftest.py — testcontainers 起完整栈
2. server/tests/e2e/test_full_pipeline.py — 上传 script → run → 验证 MinIO 产物
3. server/tests/e2e/test_retry_flow.py — 单 chunk retry → finalize
4. server/tests/e2e/test_failure_recovery.py — kill worker → 重启 → 自动恢复
5. server/tests/e2e/test_concurrency.py — 并发 5 episode → 验证 Fish API 限流
6. .github/workflows/e2e.yml — CI 跑 e2e

验收:
- 全部 e2e 测试在 CI 跑通
- 每个测试独立(不依赖前一个测试的状态)
- testcontainers 能跨平台跑(Linux + macOS)

禁止:
- 不修改任何业务代码(发现 bug 提 issue 给对应 agent)

完成后产出 worklog: docs/worklogs/A11-e2e.md
```

### 4.9 A12-Prod

```
你是 A12-Prod agent。任务:生产化打包与部署。

依赖:
- 全部完成

产出:
1. server/Dockerfile — 多阶段构建,prod 镜像 <500MB
2. whisperx-svc/Dockerfile — 同上,模型走 named volume
3. web/Dockerfile — Next.js standalone build
4. docker/docker-compose.prod.yml — 生产配置(env 走 .env / secrets)
5. docker/.env.example — 全部环境变量清单
6. scripts/backup.sh / scripts/restore.sh — Postgres + MinIO 备份脚本
7. server/api/observability.py — structlog 配置 + Prometheus metrics endpoint
8. docs/deployment.md — 部署 runbook

验收:
- docker-compose -f docker-compose.prod.yml up 全绿
- 镜像总大小 <2GB(不含 WhisperX 模型)
- 烟雾测试:创建 episode → run → 完成,全程 logs 走 stdout
- 备份脚本能跑通

禁止:
- 不改业务代码
- 不在 Dockerfile 里写 ENV 真实 secret

完成后产出 worklog: docs/worklogs/A12-prod.md
```

---

## 5. 协调协议

### 5.1 工作树隔离

每个 agent 用独立 git worktree:

```bash
git worktree add ../tts-harness-A1 -b agent/A1-infra
git worktree add ../tts-harness-A2 -b agent/A2-domain
# ...
```

Spawn agent 时用 `Agent` 工具的 `isolation: "worktree"` 参数。Agent 完成后,人工 review 分支 → 合并到 wave 集成分支 → wave 完成后合并到 main。

### 5.2 契约修改广播

任何对 §3 契约的修改都要:

1. 在 `docs/contracts/CHANGELOG.md` 写一行(日期 / 修改 / 影响 agent 列表)
2. 主会话用 `SendMessage` 通知所有相关 in-flight agent
3. 受影响 agent 必须在自己的 worklog 里 ACK

### 5.3 卡点上报

Agent 遇到卡点(决策歧义 / 契约缺失 / 工具不可用),必须:

1. 立即在 worklog 里写"卡点"段落
2. 用 `SendMessage` 上报主会话,等回复
3. 不要擅自做契约决策 — 退出而不是猜

### 5.4 Wave 集成 Gate

每个 wave 末尾,主会话执行 gate 检查:

```
[ ] 全部 agent 产出 worklog
[ ] 全部 agent 单测/集成测试通过
[ ] 全部产出文件经过 review(human-in-the-loop)
[ ] wave 集成分支 CI 通过
[ ] 打 git tag: rewrite-W{N}-complete
```

不通过则不进入下一 wave。

---

## 6. 时间与里程碑

不给绝对时间(按规则),只给里程碑顺序:

| Milestone | 完成标志 |
|---|---|
| **M0** | A0 契约文档冻结,A1 spawn |
| **M1** | dev 环境跑起来,迁移通过 |
| **M2** | 核心域 + WhisperX 服务可独立调用 |
| **M3** | 4 个 task 全部单测通过 |
| **M4** | 主 flow 端到端跑通,产物落 MinIO |
| **M5** | API + 前端对接,UI 跑通新后端 |
| **M6** | e2e 全绿,可部署 staging |

每个 M 之间是**严格门控**,不允许跳号。

---

## 7. 并行度估算

| Wave | 并行 agent 数 | 是否阻塞下游 |
|---|---|---|
| W0 | 0 (人 + 主 Claude) | 是 |
| W1 | 1 (A1) | W2 可早启动 |
| W2 | 2 (A2 + A3) | W3 强阻塞 |
| W3 | 4 (A4-A7) | W4 强阻塞 |
| W4 | 2 (A8 + A9) | W5 强阻塞(A9 阻塞 A10) |
| W5 | 2 (A10 + A11) | W6 阻塞 |
| W6 | 1 (A12) | — |

**最大并行度:4(W3)**。这是整个计划吞吐量的瓶颈点 —— 4 个 task agent 同时跑互不依赖的代码,最能体现 Agent Teams 的价值。

---

## 8. 失败模式与回退

| 失败模式 | 检测 | 回退 |
|---|---|---|
| 某 agent 产出代码不符合契约 | wave gate review | 把任务退回该 agent,附 review 反馈 |
| Wave 集成分支 CI 不过 | gate check | 找出 culprit agent 单独修;实在不行整个 wave 回退到上个 tag |
| 契约本身有缺陷 | 多个 agent 同时上报卡点 | 主会话停止 spawn,回 W0 改契约,重新广播 |
| Prefect / FastAPI 等技术栈遇到无法绕过的坑 | task agent 持续失败 | 回 ADR-001 重新评估选型(应该极少触发) |
| Agent 偏离任务范围 | worklog review | 强制重做,不接受越界产出 |

---

## 9. Worklog 模板

每个 agent 完成后必须产出 `docs/worklogs/A{N}-{name}.md`,格式:

```markdown
# A{N} {Name} — Worklog

**Agent**: A{N}
**Wave**: W{X}
**Branch**: agent/A{N}-{name}
**Status**: completed | blocked | partial

## 产物
- 列出每个文件 + 一行说明

## 关键决策
- 任何**契约之外**的设计选择,写明 why

## 放弃的方案
- 试过但放弃的方案 + 原因(避免后人重蹈)

## 卡点(如有)
- 列出遇到的契约歧义 / 工具问题 / 上游 bug

## 给下游的提示
- 下游 agent 接手时需要知道的非显然事情

## 测试
- 跑了什么测试,结果如何
```

这些 worklog 是**多 Agent 协作模式的学习产物**,review 后可用于优化未来的 spawn prompt。

---

## 10. Open Questions(W0 之前必须回答)

| # | 问题 | 默认假设 | 谁回答 |
|---|---|---|---|
| 1 | 鉴权方案 (a/b/c) | (b) shared token 起步 | 人 |
| 2 | WhisperX GPU 还是 CPU | 先 CPU,GPU Dockerfile 留 stub | 人 |
| 3 | 是否用 git worktree 隔离 agent | 是 | 人 |
| 4 | Worklog 是否进 git | 是,在 docs/worklogs/ | 人 |
| 5 | 是否需要 staging 环境 | W6 之前不需要 | 人 |
| 6 | 前端是否保留 Next.js BFF 层 | 不保留,直连 FastAPI | 人 |
| 7 | Pydantic schema 命名空间(domain.py 一个文件还是拆) | 一个文件起步,>500 行再拆 | A0 |
| 8 | Prefect work pool 类型(Process / Docker) | Process(见 ADR §4.6) | 已定 |

---

## 11. 与 ADR-001 的关系

- ADR-001 锁定**做什么 / 用什么**(技术选型 + 架构边界)
- 本文档锁定**怎么做 / 谁来做**(执行计划 + Agent 分工)
- 二者应同步演进:技术选型变 → ADR-001 改 → 本文档相应 wave 调整;执行细节变只改本文档
