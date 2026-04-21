# 配置管理设计方案

> 初稿: 2026-04-10
> 最近更新: 2026-04-21（补新变量 GROQ/STORAGE/COOKIE；修正迁移进度；P3 → P2v 术语）

## 设计原则

1. **单一配置源**：所有配置从根目录 `.env` 文件读，不散落
2. **不改代码切环境**：`.env.dev` / `.env.prod` / `.env.test` 切文件，不改代码
3. **有默认值**：不配 `.env` 也能跑，降低上手门槛
4. **三层读取**：`.env` 文件 → 环境变量 → 代码默认值（优先级从高到低）

## 配置变量全表

### 基础设施

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://harness:harness@localhost:55432/harness` | `postgresql+asyncpg://user:pass@db:5432/harness` | FastAPI, alembic |
| `MINIO_ENDPOINT` | `localhost:59000` | `minio:9000` | FastAPI |
| `MINIO_ACCESS_KEY` | `minioadmin` | `prod-key` | FastAPI |
| `MINIO_SECRET_KEY` | `minioadmin` | `prod-secret` | FastAPI |
| `MINIO_BUCKET` | `tts-harness` | `tts-harness` | FastAPI |
| `MINIO_SECURE` | `false` | `true` | FastAPI |
| `PREFECT_API_URL` | `http://localhost:54200/api` | `http://prefect:4200/api` | FastAPI (prefect mode) |
| `PREFECT_API_DATABASE_CONNECTION_URL` | `postgresql+asyncpg://prefect:prefect@prefect-db:5432/prefect` | 同 dev 思路 | docker-compose (Prefect server) |
| `PREFECT_UI_URL` | `http://localhost:54200` | — | docker-compose |

### 应用服务

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `API_PORT` | `8100` | `8000` | Makefile, Dockerfile |
| `WEB_PORT` | `3010` | `3010` | Makefile, Dockerfile |
| `WHISPERX_URL` | `http://localhost:7860` | `http://whisperx-svc:7860` 或空（prod 用 Groq） | P2v task |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8100` | `http://api:8000` | Next.js（编译时） |

### 外部服务

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `FISH_TTS_KEY` | (无默认) | `your-key` | P2 task |
| `FISH_TTS_REFERENCE_ID` | (无默认) | `voice-id` | P2 task |
| `FISH_TTS_MODEL` | `s2-pro` | `s2-pro` | P2 task |
| `GROQ_API_KEY` | (无默认，可选) | `your-groq-key` | P2v task（`WHISPERX_MODE=groq` 时） |

### 运行模式 / 鉴权 / 存储

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `TTS_USE_PREFECT` | (空 = dev mode) | `1` | FastAPI run/retry/finalize |
| `HARNESS_API_TOKEN` | (空 = 无鉴权) | `secret-token` | FastAPI auth |
| `COOKIE_SECURE` | `false` | **`true`**（HTTPS 环境必需） | `server/api/routes/keys.py:15` |
| `LOG_LEVEL` | `info` | `warning` | uvicorn |
| `STORAGE_QUOTA_GB` | 如 `20` | 生产按容量设 | `server/core/cleanup.py:75-76` |
| `STORAGE_TARGET_GB` | 如 `15` | 清理目标值 | `server/core/cleanup.py:75-76` |

### 网络 / 代理

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `HTTPS_PROXY` | (从系统继承 ClashX) | (无) | httpx (Fish API) |
| `NO_PROXY` | `localhost,127.0.0.1` | (无) | 防止 localhost 连接走代理 |

### Docker compose 端口映射

| 变量 | dev 默认值 | prod 示例 | 消费者 |
|---|---|---|---|
| `POSTGRES_PORT` | `55432` | `5432` | docker-compose |
| `MINIO_API_PORT` | `59000` | `9000` | docker-compose |
| `MINIO_CONSOLE_PORT` | `59001` | `9001` | docker-compose |
| `PREFECT_PORT` | `54200` | `4200` | docker-compose |

## 文件结构

```
tts-agent-harness/
├── .env                  ← 当前激活的配置（.gitignore，不进 git）
├── .env.dev              ← dev 环境模板（进 git） ✅ 已存在
├── .env.prod             ← prod 环境模板（进 git，不含真实 secret） ❌ 未创建，prod 目前靠 fly.toml + flyctl secrets
├── .env.test             ← test 环境模板（进 git） ❌ 未创建，测试环境共用 .env.dev
└── docker/.env.example   ← 旧残留，建议清理（已统一到根 .env）
```

> **注**：初稿规划了完整三文件模板。当前实际只有 `.env.dev` 进入仓库；prod 配置在 fly.toml 的 `[env]` + flyctl secrets 中维护。若要追平设计，需要补建 `.env.prod`/`.env.test` 并删除 `docker/.env.example`。

## 各消费者如何读取

### Makefile

```makefile
-include .env
export

API_PORT   ?= 8100
WEB_PORT   ?= 3010
```

端口与 proxy 处理从 `.env` 读。

### Docker compose

```yaml
services:
  postgres:
    ports:
      - "${POSTGRES_PORT:-55432}:5432"
```

compose 的 `--env-file` 指向根 `.env`：
```makefile
COMPOSE := docker compose --env-file .env -f docker/docker-compose.dev.yml
```

### FastAPI (server/core/db.py)

```python
import os
DATABASE_URL = os.environ.get("DATABASE_URL",
    "postgresql+asyncpg://harness:harness@localhost:5432/harness")
```

默认 fallback 为 `5432`（标准 PG 端口）；dev 通过 `.env.dev` 覆盖为 `55432`，避免和本机已装的 Postgres 冲突。

### P2v task（转写）

```python
WHISPERX_URL = os.environ.get("WHISPERX_URL", "http://localhost:7860")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
```

根据 `WHISPERX_MODE` 选择 local WhisperX 或 Groq 云端。

### Next.js（前端）

```typescript
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8100";
```

### Makefile serve target

```makefile
serve-api:
    set -a && [ -f .env ] && . ./.env; set +a; \
    NO_PROXY="localhost,127.0.0.1" \
    uvicorn server.api.main:app --port $${API_PORT:-8100}

serve-whisperx:
    if [ "$${WHISPERX_MODE}" = "docker" ]; then
        docker run ... whisperx-svc:dev
    elif [ "$${WHISPERX_MODE}" = "groq" ]; then
        echo "using Groq cloud API, no local service to start"
    else
        .venv/bin/uvicorn whisperx-svc.server:app --port 7860
    fi
```

### WhisperX 环境切换

| 变量 | 值 | 行为 |
|---|---|---|
| `WHISPERX_MODE=local` | 用 `.venv` 本地 Python 跑 | dev 默认（ARM 原生，快） |
| `WHISPERX_MODE=docker` | 用 Docker 容器跑 | 需要隔离时 |
| `WHISPERX_MODE=groq` | 走 Groq 云 API | prod 推荐（无本地依赖） |
| `WHISPERX_URL` | `http://localhost:7860` | P2v task 连接地址 |
| `GROQ_API_KEY` | `secret` | `groq` 模式必需 |

## 环境模板

### .env.dev（示意，真实见仓库）

```bash
# === Infrastructure ===
DATABASE_URL=postgresql+asyncpg://harness:harness@localhost:55432/harness
POSTGRES_PORT=55432
MINIO_ENDPOINT=localhost:59000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=tts-harness
MINIO_API_PORT=59000
MINIO_CONSOLE_PORT=59001
PREFECT_API_URL=http://localhost:54200/api
PREFECT_PORT=54200

# === Application ===
API_PORT=8100
WEB_PORT=3010
WHISPERX_URL=http://localhost:7860
WHISPERX_MODE=local
NEXT_PUBLIC_API_URL=http://localhost:8100
LOG_LEVEL=info

# === External services ===
FISH_TTS_KEY=your-key-here
# FISH_TTS_REFERENCE_ID=
# FISH_TTS_MODEL=s2-pro
# GROQ_API_KEY=   # 仅 WHISPERX_MODE=groq 时需要

# === Runtime mode / Auth ===
# TTS_USE_PREFECT=     # 空 = dev mode
# HARNESS_API_TOKEN=   # 空 = 无鉴权
COOKIE_SECURE=false

# === Storage cleanup ===
STORAGE_QUOTA_GB=20
STORAGE_TARGET_GB=15

# === Network ===
NO_PROXY=localhost,127.0.0.1
```

### .env.prod（模板，未创建文件 — 当前配置走 fly.toml + flyctl secrets）

```bash
# === Infrastructure ===
DATABASE_URL=postgresql+asyncpg://harness:${DB_PASSWORD}@postgres:5432/harness
POSTGRES_PORT=5432
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=${MINIO_KEY}
MINIO_SECRET_KEY=${MINIO_SECRET}
MINIO_BUCKET=tts-harness
MINIO_SECURE=true

# === Application ===
API_PORT=8000
WEB_PORT=3010
# WHISPERX_URL 留空 = 禁用本地；改用 Groq
WHISPERX_MODE=groq
NEXT_PUBLIC_API_URL=http://api:8000
LOG_LEVEL=warning

# === External services ===
FISH_TTS_KEY=${FISH_KEY}
GROQ_API_KEY=${GROQ_KEY}

# === Runtime mode / Auth ===
TTS_USE_PREFECT=1
HARNESS_API_TOKEN=${API_TOKEN}
COOKIE_SECURE=true     # HTTPS 必需
```

### .env.test（模板，未创建）

```bash
DATABASE_URL=postgresql+asyncpg://harness:harness@localhost:55432/harness
MINIO_ENDPOINT=localhost:59000
WHISPERX_URL=http://localhost:7860
WHISPERX_MODE=local
API_PORT=8100
NEXT_PUBLIC_API_URL=http://localhost:8100
# FISH_TTS_KEY= 需要设置才能跑真实 P2
```

## 切换环境

```bash
# 开发
cp .env.dev .env

# 生产
cp .env.prod .env
# 编辑 .env 填入真实 secret

# 测试
cp .env.test .env
```

或 Makefile 快捷命令：

```makefile
env-dev:
    cp .env.dev .env && echo "switched to dev"

env-prod:
    cp .env.prod .env && echo "switched to prod — edit .env to fill secrets"

env-test:
    cp .env.test .env && echo "switched to test"
```

## 迁移步骤状态

| # | 步骤 | 状态 |
|---|------|------|
| 1 | 创建 `.env.dev` | ✅ |
| 1 | 创建 `.env.prod` | ❌ prod 改走 fly.toml + flyctl secrets |
| 1 | 创建 `.env.test` | ❌ test 共用 .env.dev |
| 2 | 把原有 `.env` 合并到 `.env.dev` | ✅ |
| 3 | 删除 `docker/.env` / compose 读根 `.env` | ⚠️ compose 已改但 `docker/.env.example` 残留 |
| 4 | Makefile 端口从 `.env` 读 | ✅ |
| 5 | 代码默认值与 `.env.dev` 对齐 | ✅ |
| 6 | `serve-whisperx` 按 `WHISPERX_MODE` 启动 | ✅（含 groq 分支） |
| 7 | `.gitignore` 加 `.env` | ✅ |

**待收尾项**：
1. 若需 `.env.prod`/`.env.test` 进仓库，按模板创建
2. 清理 `docker/.env.example`
