# ADR-001：服务端技术选型 — Prefect 3 + FastAPI + Postgres + MinIO

| | |
|---|---|
| **状态** | Accepted |
| **日期** | 2026-04-09 |
| **影响范围** | 整个服务端架构、Docker 化部署、前端 adapter 层 |

---

## 1. 背景与目标

### 1.1 系统定位

TTS Agent Harness 是一个**多 Agent TTS 语音生产服务**：

```
脚本 JSON → P1 切分 → P2 Fish TTS 合成 → P3 WhisperX 转写 → P5 字幕分配 → P6 ffmpeg 拼接 → per-shot WAV + 字幕
```

面向内部团队，常驻部署，支持多用户并发跑多个 episode，支持人工介入（单 chunk 重试 / 多 take 选择 / 文本编辑后局部重跑）。

### 1.2 关键约束

| 维度 | 要求 |
|---|---|
| 部署 | Docker 容器化、常驻进程、可横向扩容 worker |
| 并发 | 多用户并发跑多 episode；Fish API 必须全局严格限流（防 429） |
| 状态 | 真正的数据库；可备份、可查询、可审计 |
| 失败恢复 | 自动 retry；进程崩溃后 in-flight job 自动 resume |
| 交互模式 | 支持命令式人工介入（不只是批处理） |
| P3 转写 | 独立服务、可绑 GPU、模型常驻不重复加载 |
| 进度反馈 | 实时结构化事件推送，前端不依赖轮询 |
| 产物存储 | 对象存储，不依赖宿主机本地路径 |

---

## 2. 决策

采用 **Prefect 3 + FastAPI + Postgres + MinIO** 作为服务端技术栈，前端 Next.js 退化为纯 UI 层。

### 2.1 组件清单

| 层 | 选型 | 版本 | 职责 |
|---|---|---|---|
| **UI** | Next.js | 16.x | 纯前端，通过 HTTP + SSE 与 FastAPI 通信 |
| **API 网关** | FastAPI + Uvicorn | Python 3.12 / FastAPI 0.115+ | REST API、SSE 推送、鉴权、触发 Prefect deployment |
| **Workflow 引擎** | Prefect | 3.x | flow / task 编排、retry、concurrency limit、run 历史、UI |
| **Worker 池** | Prefect Worker (Process pool) | 3.x | 真正执行 P1/P2/P5/P6 task，可横向扩容 |
| **业务数据库** | PostgreSQL | 16 | episodes / chunks / takes / stage_runs / events 业务表 |
| **Prefect 后端** | PostgreSQL（同实例不同 schema） | 16 | flow_runs / task_runs / deployments 等 Prefect 元数据 |
| **对象存储** | MinIO | RELEASE.2025+ | 音频（WAV）、字幕（SRT）、产物归档；S3 兼容 |
| **转写服务** | WhisperX (Python) | — | HTTP 常驻服务，独立容器，可绑 GPU |
| **schema 校验** | Pydantic v2（后端）+ Zod（前端） | — | 双端类型契约，OpenAPI 自动生成 |
| **共享契约** | OpenAPI schema → 前端用 `openapi-typescript` 生成 TS 类型 | — | 前后端类型一致 |
| **日志** | structlog + JSON | — | 容器化下走 stdout，由 Docker / k8s 收集 |
| **测试** | pytest（后端）+ Vitest（前端） | — | — |

---

## 3. 架构图

### 3.1 容器拓扑

```
                              ┌─────────────────────┐
                              │   Browser           │
                              │   localhost:3010    │
                              └──────────┬──────────┘
                                         │ HTTP + SSE
                                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│  docker-compose.yml                                                     │
│                                                                          │
│  ┌──────────────┐         ┌──────────────────┐                          │
│  │  next-ui     │ ──────► │  fastapi         │                          │
│  │  :3010       │ proxy   │  :8000           │ ◄──────┐                 │
│  │  (Node 22)   │         │  (Python 3.12)   │        │ events SSE      │
│  └──────────────┘         └────────┬─────────┘        │                 │
│                                    │                  │                 │
│                                    │ trigger          │                 │
│                                    │ run_deployment() │                 │
│                                    ▼                  │                 │
│                           ┌──────────────────┐        │                 │
│                           │  prefect-server  │        │                 │
│                           │  :4200           │        │                 │
│                           │  (UI + API)      │        │                 │
│                           └────────┬─────────┘        │                 │
│                                    │                  │                 │
│                                    ▼                  │                 │
│              ┌─────────────────────────────────┐      │                 │
│              │  postgres :5432                 │      │                 │
│              │  ┌──────────┐  ┌──────────────┐ │      │                 │
│              │  │ business │  │  prefect     │ │      │                 │
│              │  │ schema   │  │  schema      │ │ ◄────┘                 │
│              │  └──────────┘  └──────────────┘ │ LISTEN/NOTIFY           │
│              └─────────────────────────────────┘                        │
│                                    ▲                                    │
│                                    │ read/write business state          │
│                                    │                                    │
│              ┌─────────────────────┴───────────────┐                    │
│              │                                     │                    │
│   ┌──────────────────┐                    ┌──────────────────┐          │
│   │ prefect-worker-1 │  ...  ×N           │ prefect-worker-N │          │
│   │ (Process pool)   │                    │                  │          │
│   └────────┬─────────┘                    └────────┬─────────┘          │
│            │                                       │                    │
│            │ tasks: p1/p2/p5/p6                    │                    │
│            ▼                                       ▼                    │
│      ┌──────────┐                            ┌──────────────┐           │
│      │  minio   │ ◄──── 音频/字幕产物 ────►  │ whisperx-svc │           │
│      │  :9000   │                            │ :7860        │           │
│      └──────────┘                            │ (CPU/GPU)    │           │
│                                              └──────────────┘           │
│                                                                          │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.2 容器清单

| 容器 | 镜像 | 端口 | 资源建议 | 状态 |
|---|---|---|---|---|
| `next-ui` | 自建（Node 22） | 3010 | 256MB | stateless |
| `fastapi` | 自建（Python 3.12） | 8000 | 512MB | stateless |
| `prefect-server` | `prefecthq/prefect:3-latest` | 4200 | 512MB | stateless（state 在 PG） |
| `prefect-worker` ×N | 自建（含 ffmpeg + Python deps） | — | 1-2GB / worker | stateless |
| `postgres` | `postgres:16-alpine` | 5432 | 1GB + 卷 | **stateful** |
| `minio` | `minio/minio:latest` | 9000/9001 | 512MB + 卷 | **stateful** |
| `whisperx-svc` | 自建（含 WhisperX + 模型缓存） | 7860 | 4-8GB（CPU）/ GPU | stateful（模型缓存卷） |

---

## 4. 关键设计决策

这一节是这份 ADR 的**核心**，记录的是不写下来一年后会忘掉为什么这么做的非显然决策。

### 4.1 业务状态与 Workflow 状态分离

**决策**：业务领域对象（episodes / chunks / takes）的 source of truth 是 **Postgres 业务 schema**，由 FastAPI 读写。Prefect 只负责"跑 task"和"记录 task run 历史"，不负责"业务对象现在是什么状态"。

**为什么**：
- Prefect 的 `flow_run` / `task_run` 是**执行历史**，不是**领域状态**。把业务状态塞进 Prefect tag/parameter 是反模式。
- FastAPI 要响应"列出所有 episode" / "拿 chunk #7 的当前 take" 这类请求，**不能依赖 Prefect API**——Prefect API 是为 workflow 管理设计的，不是为业务查询设计的。
- 用户对 chunk #7 retry 时，FastAPI 直接 `INSERT INTO takes ...`，再触发一个**单 task 的 mini flow** 跑 P2，跑完 worker 把新 take 的 metadata 写回 `takes` 表。Prefect 全程不知道"take 是什么"。

**反模式预警**：以后任何人想"把 episode 状态存到 Prefect flow run 的 state 字段里"——拒绝。

### 4.2 per-stage 是 task，per-episode 是 flow，retry 是 mini-flow

**决策**：

```python
@flow(name="run-episode")
def run_episode_flow(ep_id: str):
    chunks = p1_chunk(ep_id)                      # 1 task
    p2_results = p2_synth.map(chunks)             # fan-out
    p3_results = p3_transcribe.map(p2_results)    # fan-out
    p5_results = p5_subtitles.map(p3_results)     # fan-out
    p6_concat(ep_id, p5_results)                  # 1 task

@flow(name="retry-chunk-stage")
def retry_chunk_stage_flow(ep_id: str, cid: str, from_stage: str, cascade: bool):
    # 单 chunk 局部重跑,不动其他 chunk
    ...
```

**为什么不把 retry 塞进主 flow**：
- 主 flow 的 `.map()` 是**幂等批处理**模型；交互式 retry 是**带 in-flight 状态的命令**。塞一起会让 flow 变得无法恢复（"我现在跑的是初始 run 还是某次 retry？"）。
- 拆成 mini-flow 后：主 flow 干净、retry flow 也干净，**Prefect UI 上能清楚看到每次 retry 是独立 run**，便于审计。
- 代价：要维护两套 flow。可接受。

### 4.3 Fish API 限流靠 Prefect Concurrency Limit，不自建队列

**决策**：

```python
@task(tags=["fish-api"], retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=2))
def p2_synth(chunk: ChunkInput) -> P2Result:
    ...
```

```bash
prefect concurrency-limit create fish-api 3
```

**为什么**：
- Fish API 的并发上限是硬约束，在框架层声明式表达比在业务代码里手写 token bucket / leaky bucket 更可靠、更易审计。
- Prefect 的 concurrency limit 是全局一致的，无论几个 worker 副本都生效，不需要 Redis 分布式锁。
- 未来要加新的限流维度（"每个用户最多 5 个并发 episode"）也是同样模式：`tags=["user:{uid}"]`。
- **Prefect UI 上能直接看到被 limit 卡住的 task 队列**，不用自己埋 metrics。

### 4.4 SSE 推送靠 Postgres LISTEN/NOTIFY，不引 Redis

**决策**：worker 完成 task 后，在事务里 `NOTIFY episode_events, '<json payload>'`。FastAPI 用 asyncpg 持有一个 `LISTEN` 连接，把通知 fan-out 到所有订阅该 episode 的 SSE client。

**为什么**：
- 已经有 Postgres，不用为了 pub/sub 引 Redis 多一个容器。
- 单 FastAPI 实例够用（内部服务规模）。**如果未来 FastAPI 要多副本**，再升级到 Redis Pub/Sub 或 NATS——届时迁移成本不高，因为 SSE 推送层本身是薄的。
- 备选方案是用 Prefect 的 webhook / event hooks 直接推到 FastAPI，但多一跳网络、且 Prefect event 模型 3.x 还在演进，不如 Postgres 通知稳。

**未来扩展触发条件**：FastAPI 副本数 > 1 时，切 Redis Pub/Sub。

### 4.5 产物存 MinIO，不存卷挂载

**决策**：所有 WAV / SRT / 中间产物用 S3 协议存 MinIO，**不用** Docker volume 挂载共享目录。

**为什么**：
- 多个 worker 容器要并发读写产物，共享卷有 NFS-style 一致性问题。
- 未来上 K8s / 云部署时，对象存储是默认假设；现在用 MinIO 抹平接口，未来切 S3/R2/OSS 改个 endpoint 即可。
- 业务表里只存 `s3://tts-harness/episodes/{ep_id}/chunks/{cid}/takes/{take_id}.wav` 这种 URI，不存绝对路径。
- 代价：本地开发要起 MinIO 容器。可接受（compose 自动起）。

**例外**：WhisperX 的模型缓存（几 GB）用 named volume 挂载到 `whisperx-svc`，避免每次重建容器都重下模型。

### 4.6 Prefect Worker 用 Process pool，不用 Docker pool

**决策**：worker 类型选 **Process worker**（一个 worker 容器内 fork 子进程跑 task），不是 Docker worker（每个 task 起一个新容器）。

**为什么**：
- Process worker 启动延迟 < 100ms，Docker worker 每个 task 启动延迟 1-3s。对每 episode 几十个 task 的工作量，Docker worker 累计延迟无法接受。
- Docker-in-Docker 复杂度高，不值得。
- 横向扩容靠加 worker 容器副本，不靠单 worker 内 task 隔离。
- 代价：同一 worker 内 task 共享 Python 进程的依赖版本——这正好是我们要的（统一环境）。

### 4.7 FastAPI 与 Prefect 的边界

**决策**：

| 操作 | 谁负责 |
|---|---|
| `GET /episodes` | FastAPI 直查 Postgres 业务表 |
| `GET /episodes/{id}` | FastAPI 直查 Postgres |
| `POST /episodes` (创建) | FastAPI 写 `episodes` 表 + 上传 script.json 到 MinIO |
| `POST /episodes/{id}/run` | FastAPI 调用 `run_deployment("run-episode")` 触发 flow |
| `POST /episodes/{id}/chunks/{cid}/retry` | FastAPI 写 `takes` 表 + 触发 `retry-chunk-stage` mini-flow |
| `GET /episodes/{id}/stream` (SSE) | FastAPI 持有 LISTEN 连接，推送 |
| 跑 P1/P2/P5/P6 | Prefect worker |
| 看 flow 执行历史 / debug 失败 task | Prefect UI（直接给开发者用，不暴露给业务用户） |

**为什么 Prefect UI 不直接给业务用户**：
- Prefect UI 是面向"workflow 工程师"的，不是面向"内容编辑"的。
- 业务用户要看的是"chunk #7 的第 3 个 take 听起来怎么样"，不是"task_run_id=abc123 的 state 是 Completed"。
- **Prefect UI 给我自己 debug 用，前端给业务用户用**。两套界面服务两种角色。

### 4.8 P3 WhisperX 保持独立 HTTP 服务，不进 Prefect task

**决策**：P3 不写成 `@task def p3_transcribe(...)`，而是 worker 内的 task **HTTP 调用** `whisperx-svc:7860`。

**为什么**：
- WhisperX 模型加载要几十秒，每次 task 启动都加载不可接受。
- 模型文件几 GB，不应该跟 worker 镜像绑在一起。
- 未来要绑 GPU，独立容器更容易（不用让所有 worker 都装 CUDA）。
- 代价：多一跳网络。可接受，因为 WhisperX 推理本身就是秒级。

---

## 5. 数据模型草图

### 5.1 业务 schema（Postgres `business`）

```sql
-- episodes
CREATE TABLE episodes (
  id              TEXT PRIMARY KEY,           -- 用户提供的 slug
  title           TEXT NOT NULL,
  description     TEXT,
  status          TEXT NOT NULL,              -- empty/ready/running/failed/done
  script_uri      TEXT NOT NULL,              -- s3://.../script.json
  config          JSONB NOT NULL DEFAULT '{}',-- per-episode pipeline 配置覆盖
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at     TIMESTAMPTZ,
  metadata        JSONB NOT NULL DEFAULT '{}'
);

-- chunks
CREATE TABLE chunks (
  id                TEXT PRIMARY KEY,         -- '{ep_id}:{cid}'
  episode_id        TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  shot_id           TEXT NOT NULL,
  idx               INT NOT NULL,             -- shot 内序号
  text              TEXT NOT NULL,            -- P1 切分原文
  text_normalized   TEXT NOT NULL,            -- TTS 输入
  subtitle_text     TEXT,                     -- 可选,字幕显示
  status            TEXT NOT NULL,            -- pending/synth_done/transcribed/failed
  selected_take_id  TEXT,
  boundary_hash     TEXT,
  char_count        INT NOT NULL,
  last_edited_at    TIMESTAMPTZ,
  metadata          JSONB NOT NULL DEFAULT '{}',
  UNIQUE(episode_id, shot_id, idx)
);

-- takes
CREATE TABLE takes (
  id            TEXT PRIMARY KEY,             -- ulid
  chunk_id      TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  audio_uri     TEXT NOT NULL,                -- s3://.../take_xxx.wav
  duration_s    REAL NOT NULL,
  params        JSONB NOT NULL DEFAULT '{}',  -- temperature/top_p/seed
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- stage_runs (per chunk per stage 的最新一次执行)
CREATE TABLE stage_runs (
  chunk_id       TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  stage          TEXT NOT NULL,               -- p2/check2/p3/check3/p5
  status         TEXT NOT NULL,               -- pending/running/ok/failed
  attempt        INT NOT NULL DEFAULT 0,
  started_at     TIMESTAMPTZ,
  finished_at    TIMESTAMPTZ,
  duration_ms    INT,
  error          TEXT,
  log_uri        TEXT,                        -- s3://.../logs/{cid}/{stage}.log
  prefect_task_run_id  UUID,                  -- 反查 Prefect UI
  stale          BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (chunk_id, stage)
);

-- events (append-only,用于 SSE 推送 + 审计)
CREATE TABLE events (
  id             BIGSERIAL PRIMARY KEY,
  episode_id     TEXT NOT NULL,
  chunk_id       TEXT,
  kind           TEXT NOT NULL,               -- stage_started/stage_finished/take_appended/...
  payload        JSONB NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_episode_idx ON events(episode_id, id DESC);
```

**触发器**：`events` 表 INSERT 后自动 `pg_notify('episode_events', json_build_object('ep', NEW.episode_id, 'id', NEW.id)::text)`。FastAPI 收到通知后用 id 反查具体 payload。

---

## 6. 仓库结构

```
tts-agent-harness/
├── web/                      # Next.js UI(纯前端)
│   ├── app/
│   │   └── page.tsx
│   ├── components/
│   └── lib/
│       ├── ports/            # 业务接口契约
│       ├── adapters/
│       │   └── api/          # HTTP client 实现 ports,对接 FastAPI
│       └── types.ts          # 由 OpenAPI 自动生成校验
│
├── server/                   # Python 服务端 monorepo
│   ├── api/                  # FastAPI 应用
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── sse.py            # LISTEN/NOTIFY → SSE
│   │   ├── deps.py
│   │   └── tests/
│   ├── flows/                # Prefect flows + tasks
│   │   ├── run_episode.py
│   │   ├── retry_chunk.py
│   │   ├── tasks/
│   │   │   ├── p1_chunk.py
│   │   │   ├── p2_synth.py
│   │   │   ├── p5_subtitles.py
│   │   │   └── p6_concat.py
│   │   └── tests/
│   ├── core/                 # 业务逻辑(被 api + flows 共用)
│   │   ├── models.py         # SQLAlchemy / SQLModel
│   │   ├── repositories.py
│   │   ├── storage.py        # MinIO client wrapper
│   │   ├── domain.py         # Pydantic schemas (= 前端契约)
│   │   └── events.py         # 写 events 表 + NOTIFY
│   ├── migrations/           # alembic
│   ├── pyproject.toml
│   └── Dockerfile
│
├── whisperx-svc/             # P3 转写独立服务
│   ├── server.py
│   ├── pyproject.toml
│   └── Dockerfile
│
├── docker/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   └── docker-compose.prod.yml
│
└── docs/
    └── adr/
        └── 001-server-stack.md  # 本文件
```

---

## 7. 实施波次

详细的多 Agent 并行执行计划见 [`002-rewrite-plan.md`](./002-rewrite-plan.md)。

本节只列出波次目标与里程碑：

| Wave | 目标 | 里程碑（DoD） |
|---|---|---|
| **W0 基础设施** | docker-compose dev 环境、Postgres schema、MinIO bucket、Prefect server | `docker-compose up` 全绿；alembic migration 通过；Prefect UI 可访问 |
| **W1 核心域** | SQLAlchemy 模型 + repositories + MinIO storage wrapper + Pydantic schemas + events/NOTIFY | 单测覆盖 CRUD；events 表 INSERT 能被 LISTEN 收到 |
| **W2 Pipeline tasks** | P1 / P2 / P5 / P6 用 Python 实现为 Prefect task；WhisperX 独立服务化 | 每个 task 独立可跑；whisperx-svc 通过 health check |
| **W3 编排与 API** | `run-episode` flow + `retry-chunk-stage` mini-flow + FastAPI routes + SSE | 端到端：API 创建 episode → 触发 flow → 完整产物在 MinIO；SSE 实时推送 stage 状态 |
| **W4 前端对接** | 前端 `adapters/api/` HTTP client；OpenAPI → TS 类型生成；CI diff 校验 | UI 跑通新后端；类型契约 CI 通过 |
| **W5 生产化** | 多 take / TakeSelector / Process work pool / prod Dockerfile / 监控埋点 | 可部署到 staging；kill -9 自动恢复；备份/恢复演练通过 |

每个 wave 末尾打 git tag，可独立回退。

---

## 8. 评估过的备选方案

### 8.1 Hono + 自建 SQLite queue（Node 全栈）

**为什么放弃**：
- 自建 queue / retry / concurrency limit 是**重新发明 Prefect 已有的轮子**，不值得
- 单文件 SQLite 不适合容器化多 worker 并发
- 没有现成的 workflow UI，要自己写大量 stage 进度展示组件
- WhisperX 强绑 Python 生态，跨语言 RPC 比同语言直接 import 更复杂

**何时会回头选它**：如果未来发现 Prefect Server 维护成本高、且 workflow 复杂度根本用不上 DAG —— 但目前看不会。

### 8.2 Temporal

**为什么放弃**：
- 比 Prefect 重得多：Temporal Server + History Service + Matching Service + Worker，组件多
- SDK 心智模型陡（activity vs workflow vs signal vs query）
- 强一致性保证对内部工具来说是 overkill
- Python SDK 体验不如 Prefect 流畅

**何时会回头选它**：
- 跨语言 worker 必须共享 workflow（Node + Python + Go 同一个 flow）
- 多租户 SaaS 要严格隔离与配额
- 单个 workflow 跨天 / 跨周，要 SAGA 补偿模式

### 8.3 FastAPI + Dramatiq/Celery + Postgres（无 Prefect）

**为什么放弃**：
- 失去 workflow UI、task tree 可视化
- DAG 依赖、`.map()` fan-out、concurrency tag 都要自己实现
- retry 策略要自己写
- 优势仅在"少一个守护进程"，对容器化部署来说收益微小

**何时会回头选它**：如果 pipeline 退化成"一串顺序 task，没有 fan-out"，Prefect 就成了过度工程。

### 8.4 Airflow

**为什么放弃**：
- 为 ETL / 数据工程设计，触发延迟高（分钟级）
- DAG 是静态的，per-chunk 动态 fan-out 不优雅
- 部署组件比 Prefect 还多

### 8.5 Next.js Route Handler + 文件系统状态

**为什么放弃**：
- Next.js Route Handler 是无状态短请求模型，承载不了长任务、进程锁、in-flight job 状态
- 文件系统作为状态源无法保证多 worker 并发下的事务性
- 容器化部署后宿主机本地路径不可依赖

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Prefect 3 是较新的版本，社区资料少于 2.x | 学习曲线陡，遇 bug 难搜 | 锁定 minor 版本；遇到坑直接读源码（Python 无门槛）；领域代码不绑死 Prefect API，保留迁移到 Temporal 的退路 |
| MinIO 在本地开发增加启动复杂度 | 新人上手慢 | docker-compose 一键起；提供 `make dev` 封装 |
| Postgres LISTEN/NOTIFY 单连接瓶颈 | FastAPI 多副本时失效 | 单副本时不会触发；触发时切 Redis Pub/Sub，迁移成本可控 |
| Prefect Worker 镜像体积大（含 ffmpeg + Python deps + 业务代码） | CI/CD 慢 | 多阶段构建；ffmpeg 用基础镜像层缓存；业务代码层放最后 |
| 业务表与 Prefect 表同一 Postgres 实例，互相影响 | 一个 schema 重负载拖慢另一个 | 起步阶段够用；负载上来后用 Postgres 多 schema + connection pool 隔离，再不够拆实例 |
| WhisperX 服务挂掉导致 P3 task 失败 | 整个 flow 卡住 | P3 task `retries=5` + WhisperX 容器加 health check + restart policy；考虑加熔断器 |
| 前端 TS 类型与 FastAPI OpenAPI 漂移 | 类型不一致，运行时报错 | CI 步骤：从 OpenAPI 生成 TS 类型，作为 source of truth；前端 import 生成产物 |

---

## 10. 暂未决定的问题

这些问题不阻塞 ADR 通过，但需要在 Wave 1-2 之前回答：

1. **鉴权方案**：内部服务先做最简单的 (a) 不鉴权 / (b) 单 shared token / (c) OIDC 接公司 SSO？倾向 (b) 起步，预留 (c) 接口。
2. **多用户隔离粒度**：episode 是否要绑 owner？倾向 Wave 5 加，schema 预留 `owner_id` 字段。
3. **WhisperX GPU vs CPU**：部署目标硬件是否有 GPU？影响 whisperx-svc Dockerfile 和模型选择，Wave 0 时确认。
4. **MinIO 路径布局规范**：`s3://tts-harness/episodes/{ep_id}/...` 的具体子结构需要在 Wave 1 落定，避免后期迁移。
5. **Prefect deployment 的 schedule 需求**：现在没有定时任务需求，但保留可能性（比如"每天扫一次失败 episode 自动 retry"）。
6. **日志保留策略**：events 表会无限增长，需要定期归档/分区。Wave 5 之前不处理。
7. **前端 BFF 还是直连**：Next.js 是否保留 `/api/*` 作为 thin BFF（用于 cookie 处理 / token 注入）？倾向直连 FastAPI，FastAPI 自己处理 CORS。如果鉴权选 OIDC 再考虑加 BFF。
8. **测试数据策略**：集成测试要不要起真的 Postgres + MinIO + Prefect？倾向 testcontainers-python，慢但真实。

---

## 11. 验收标准

这份 ADR 的实施被认为完成，当且仅当：

- [ ] `docker-compose up` 一条命令起齐全部容器，全绿
- [ ] 通过 FastAPI 创建 episode → 触发 run → 在 MinIO 看到完整 P1-P6 产物
- [ ] 前端 SSE 通道实时显示 stage 进度，无需轮询
- [ ] Fish API 并发被严格限制在 concurrency limit 内（从 Prefect UI 与日志可验证）
- [ ] 单 chunk retry 流程：编辑 → retry → 听新 take → finalize → 下游级联 OK
- [ ] worker 容器 kill -9 后，未完成的 flow run 在 worker 重启后自动恢复
- [ ] Postgres + MinIO 卷备份/恢复演练通过
- [ ] OpenAPI → TS 类型生成 CI 步骤通过

---

## 12. 参考

- Prefect 3 文档：https://docs.prefect.io/3.0/
- FastAPI 文档：https://fastapi.tiangolo.com/
- MinIO 文档：https://min.io/docs/minio/linux/index.html
- Postgres LISTEN/NOTIFY：https://www.postgresql.org/docs/16/sql-notify.html
- 配套实施计划：[`002-rewrite-plan.md`](./002-rewrite-plan.md)
