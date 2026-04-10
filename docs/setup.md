# Dev Setup — TTS Agent Harness

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop | 24+ | `docker compose` V2 |
| Python | 3.11+ | 3.14 有 wheel 兼容问题，推荐 3.11/3.12 |
| Node.js | 22+ | Next.js 16 要求 |
| pnpm | 10+ | 前端包管理 |
| ffmpeg | 7+ | P6 拼接需要 (`brew install ffmpeg`) |
| GNU Make | any | — |

## 端口表

| 端口 | 服务 | 说明 |
|---|---|---|
| **3010** | Next.js UI | 前端 |
| **8100** | FastAPI | 后端 API + SSE |
| **55432** | PostgreSQL | 业务数据库 |
| **59000** | MinIO API | S3 兼容对象存储 |
| **59001** | MinIO Console | Web 管理界面 |
| **54200** | Prefect Server | Workflow UI + API |
| 7860 | WhisperX | 转写服务（独立部署，可选） |

> 端口有意使用非标准映射（55432 而非 5432）以避免与本机已有服务冲突。

## 快速开始

```bash
# 1. 起 Docker 基础设施（Postgres + MinIO + Prefect）
make dev

# 2. 安装 Python 依赖
python3.11 -m venv .venv-server
source .venv-server/bin/activate
pip install -e 'server[dev]'

# 3. 运行数据库迁移
make migrate

# 4. 安装前端依赖
cd web && pnpm install && cd ..

# 5. 一键启动后端 + 前端
make serve

# 6. 打开浏览器
make open
```

## 日常使用

```bash
# 启动全部（docker infra 已在跑的话直接起应用）
make serve

# 停止应用（不停 docker）
make stop

# 停止全部（含 docker）
make down

# 看日志
tail -f /tmp/tts-harness-api.log   # 后端
tail -f /tmp/tts-harness-web.log   # 前端
make logs                           # Docker 容器
```

## 测试

```bash
make test         # 单元 + 集成测试（不含 e2e）
make test-e2e     # e2e 测试（需要 dev stack 在跑）
make test-live    # 真 HTTP e2e（自动起 uvicorn）
make test-all     # 全量
make tsc          # TypeScript 类型检查
```

## 类型生成

后端 Pydantic 模型变更后，重新生成前端类型：

```bash
make gen-types    # domain.py → openapi.json → openapi.d.ts
make tsc          # 验证一致性
```

## 环境变量

`make serve` 自动设置全部环境变量，不需要手动 export。关键变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://harness:harness@localhost:55432/harness` | 自动设置 |
| `MINIO_ENDPOINT` | `localhost:59000` | 自动设置 |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8100` | 自动设置 |
| `FISH_TTS_KEY` | — | 需要手动设置才能调用 Fish API |
| `HARNESS_API_TOKEN` | — | 不设则 dev mode（允许所有请求） |

## 重要：ClashX 代理

本机的 `HTTPS_PROXY` / `ALL_PROXY` 环境变量会干扰 uvicorn 和 asyncpg 的 localhost 连接。`make serve` 已自动清除这些变量。如果手动启动后端，需要：

```bash
env -u HTTPS_PROXY -u ALL_PROXY uvicorn server.api.main:app --port 8100
```

## 故障排查

| 问题 | 原因 | 解决 |
|---|---|---|
| API 500 "password authentication failed" | `DATABASE_URL` 端口不对或未设置 | 用 `make serve`，它自动设置正确端口 |
| 前端 sidebar 空白 | `NEXT_PUBLIC_API_URL` 未设置或指向错误端口 | 用 `make serve` 重启前端 |
| `address already in use` | 端口被占 | `make stop` 先清理，或修改 `API_PORT` |
| asyncpg SOCKS proxy error | ClashX 代理被继承 | `make serve` 已处理；手动启动需 `env -u HTTPS_PROXY` |
| Docker credential helper | PATH 缺少 Docker Desktop bin | `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"` |
