# 部署指南

## 架构

```
浏览器 → Fly.io (nrt)
           ├─ Caddy (:8080) ─── 反向代理统一入口
           │   ├─ /episodes/* → FastAPI (:8100)
           │   ├─ /audio/*    → FastAPI (:8100)
           │   ├─ /healthz    → FastAPI (:8100)
           │   └─ /*          → Next.js (:3010)
           ├─ Fly Postgres    ─── hiveden-tts-db.flycast:5432
           └─ Tigris (S3)     ─── fly.storage.tigris.dev
```

单容器运行 Caddy + FastAPI + Next.js（supervisor 管理），Fly Postgres 和 Tigris 为独立服务。

## 基础设施

| 组件 | 服务 | 配置 | 费用 |
|------|------|------|------|
| 应用 | Fly.io Machine | shared-cpu-1x, 2GB RAM, nrt | ~$7/月 |
| 数据库 | Fly Postgres (unmanaged) | shared-cpu-1x, 256MB, 1GB vol | ~$2/月 |
| 对象存储 | Tigris (S3-compatible) | 免费额度 | $0 |
| **总计** | | | **~$9/月** |

## 环境变量 & Secrets

通过 `flyctl secrets` 管理，不进代码：

| Secret | 必需 | 说明 |
|--------|------|------|
| `DATABASE_URL` | 是 | Fly Postgres attach 时自动设置 |
| `MINIO_ENDPOINT` | 是 | `fly.storage.tigris.dev` |
| `MINIO_ACCESS_KEY` | 是 | Tigris access key |
| `MINIO_SECRET_KEY` | 是 | Tigris secret key |
| `MINIO_BUCKET` | 是 | `hiveden-tts-storage` |
| `MINIO_SECURE` | 是 | `true` |
| `GROQ_API_KEY` | 否 | 服务端 ASR，不设则用户需自带 |

**不设 `FISH_TTS_KEY`** — 用户在页面自行配置，避免白嫖额度。

`fly.toml` 中的 env（非敏感）：

```toml
[env]
  LOG_LEVEL = 'info'
  WHISPERX_URL = ''
  CORS_ORIGINS = ''
```

## Dockerfile 要点

两阶段构建：

1. **Stage 1** (`node:20-slim`) — 构建 Next.js standalone
2. **Stage 2** (`python:3.11-slim`) — 运行时，通过 nodesource 安装 Node 20

关键设计决策：

- `NEXT_PUBLIC_API_URL=` 空字符串 → 前端用相对路径，同域访问无需 CORS
- Caddy 静态二进制下载，不走 apt
- Node 20 通过 nodesource 安装（非 Stage 1 COPY binary），确保动态链接库完整
- `deploy/start.sh` 启动时先跑 `alembic upgrade head` 再启动 supervisor

## DB URL 兼容处理

Fly Postgres 给的 URL 格式：
```
postgres://user:pass@host:5432/db?sslmode=disable
```

asyncpg 需要：
```
postgresql+asyncpg://user:pass@host:5432/db?ssl=disable
```

`server/core/db.py` 和 `server/migrations/env.py` 中 `_database_url()` / `_resolve_url()` 自动转换：
- `postgres://` → `postgresql+asyncpg://`
- `?sslmode=disable` → `?ssl=disable`

SSE listener（`server/api/sse.py`）使用 raw asyncpg，需额外处理 `ssl=False` 参数。

## Caddy 路由

`deploy/Caddyfile` 将所有请求统一到 :8080：

- `/episodes` + `/episodes/*` → FastAPI（注意需要两条规则，`/*` 不匹配裸路径）
- `/audio/*`、`/healthz`、`/docs`、`/openapi.json` → FastAPI
- 其余 → Next.js

同域部署后 CORS 不再需要（`CORS_ORIGINS=''`），但本地开发仍保留默认 `localhost:3010`。

## CI/CD

`.github/workflows/deploy.yml` — push main 自动部署：

```yaml
on:
  push:
    branches: [main]
```

需要 GitHub repo secret：`FLY_API_TOKEN`（通过 `flyctl tokens create deploy` 生成）。

## 手动部署

```bash
flyctl deploy --app hiveden-tts
```

## 常见问题

### 启动后 machine 立即停止

查日志 `flyctl logs --app hiveden-tts --no-tail`，常见原因：
- DB migration 失败（URL 格式、网络不通）
- Next.js server.js 路径错误
- Python 依赖缺失

### 访问慢（首次）

`auto_stop_machines = 'stop'` 导致冷启动。首次请求需等 machine 启动（~3-5s）。如需常驻：

```toml
min_machines_running = 1  # 保持至少一台运行
```

### 本地 Docker 构建

本地构建需代理（npm/pip 下载），但 Docker BuildKit 中 `host.docker.internal` 不稳定。建议直接用 `flyctl deploy` 远端构建（Depot，海外无需代理）。

如需本地构建，在 Dockerfile 中声明：
```dockerfile
ARG HTTP_PROXY
ARG HTTPS_PROXY
ENV http_proxy=$HTTP_PROXY https_proxy=$HTTPS_PROXY
```
构建时传入 `--build-arg HTTP_PROXY=http://host.docker.internal:7890`。

### Secrets 管理

```bash
# 查看
flyctl secrets list --app hiveden-tts

# 设置
flyctl secrets set KEY=value --app hiveden-tts

# 删除
flyctl secrets unset KEY --app hiveden-tts
```
