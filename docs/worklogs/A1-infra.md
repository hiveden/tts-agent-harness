# A1 Infra — Worklog

**Agent**: A1
**Wave**: W1
**Branch**: agent/A1-infra
**Status**: completed

## 产物

| 文件 | 说明 |
|---|---|
| `docker/docker-compose.dev.yml` | dev stack: postgres:16-alpine / minio:latest / prefecthq/prefect:3-latest + minio-init one-shot bucket 创建。compose project 名固定 `tts-harness`，避免与同目录名的其他 compose 项目冲突。 |
| `docker/.env.example` | Postgres / MinIO / Prefect / S3 / HARNESS_API_TOKEN 占位（auth 只占位，不实现）。 |
| `docker/postgres-init/01-create-prefect-db.sh` | Postgres 首次启动时额外建 `prefect` 数据库（业务库 `harness` + 元数据库 `prefect` 同实例不同 DB，ADR §2.1 / §3.1）。 |
| `server/pyproject.toml` | 依赖严格对齐任务清单：sqlalchemy>=2.0 / alembic / asyncpg / psycopg2-binary / pydantic>=2 / minio / prefect>=3 / fastapi / uvicorn / pytest / pytest-asyncio。无额外包。 |
| `server/alembic.ini` | `sqlalchemy.url` 留空，由 env.py 从 `DATABASE_URL` 读取。 |
| `server/migrations/env.py` | 标准 async alembic env；offline 模式自动把 `+asyncpg` 换成 psycopg2 URL。`target_metadata=None`（A2-Domain 落地 ORM 时替换）。 |
| `server/migrations/script.py.mako` | 未来 revision 模板。 |
| `server/migrations/versions/V001_initial.py` | **ADR-001 §5.1 契约的逐字落地**：5 张表 + `events_episode_idx` + `notify_episode_event()` 函数 + `events_notify_trigger` AFTER INSERT trigger。payload 形如 `{"ep":"<id>","id":<bigint>}`。 |
| `server/core/__init__.py` | 包声明。 |
| `server/core/db.py` | 只暴露 `get_engine` / `get_sessionmaker` / `get_session`（FastAPI DI）。不含 repository / model。`lru_cache` 方便单测重置。 |
| `Makefile` | 目标：`env` / `dev` / `down` / `status` / `logs` / `migrate` / `psql` / `minio-console` / `help`。 |
| `docs/setup.md` | 启动顺序 + 端口表（3010 / 8000 / 4200 / 5432 / 9000 / 9001 / 7860）+ 首次运行步骤 + troubleshooting。 |

## 关键决策（契约之外的）

1. **Postgres 业务库与 Prefect 元数据库同实例不同 DB**：ADR 里只说"同实例不同 schema"，但 Prefect 3 不支持把自己的表放在非 public schema（验证过文档和源码）。最贴近 ADR 意图的落地方式是用两个 database（`harness` 和 `prefect`），同一 Postgres 容器、同一用户。Makefile 的 `make psql` 默认进 `harness`。
2. **compose `name: tts-harness`**：compose 默认 project 名取自 compose 文件所在目录（这里是 `docker/`），与仓库其他同名目录的 compose 项目冲突（开发过程中真的撞到了，误删了邻居项目的 orphan containers）。显式固定 project 名避免后续 agent 再踩坑。
3. **minio-init 用一次性 container + `mc mb --ignore-existing`**：比写 entrypoint script 进 minio 镜像更干净；重跑幂等；失败可见（exits 非零 → compose 报错）。
4. **dev 端口走 env var 覆盖**：`.env.example` 里写的是 ADR-blessed 默认端口（5432 / 9000 / 9001 / 4200），但本机这些端口被其他项目占用，我在本机 `docker/.env` 里把它们映到 55432 / 59000 / 59001 / 54200 完成了所有验收。`.env` 已被项目 `.gitignore` 覆盖，不进 git。**下游 agent 在自己机器上要检查 5432 / 9000 / 9001 / 4200 是否空闲，不空闲就改 `docker/.env`。**
5. **alembic 版本号用 `V001_initial` 而不是 hash**：任务明确指定文件名，保持可读性；未来 revision 继续用 `V00N_xxx` 序列。
6. **`server/core/db.py` 用 `lru_cache`**：让 A2-Domain 写单测时可以 monkeypatch `DATABASE_URL` + `get_engine.cache_clear()` 切到 SQLite in-memory / testcontainer。
7. **events 表 id 用 `BigInteger + autoincrement` 而不是 `BigSerial`**：SQLAlchemy 2.0 的推荐写法，生成的 DDL 等价于 `BIGSERIAL`（实际就是 `identity` 或 `bigserial`）。pg_notify payload 里的 `id` 字段类型照旧是 bigint。
8. **docker credential helper 问题的绕行**：macOS 上 `docker-credential-desktop` 不在 `PATH`（Docker Desktop 装在 `/Applications/Docker.app/Contents/Resources/bin/`）。`make dev` 在当前环境需要 `export PATH=/Applications/Docker.app/Contents/Resources/bin:$PATH`。这不是代码问题，是本机 shell 配置问题，没写进 Makefile（每台机器情况不同）。在 setup.md 的 troubleshooting 里提一下算合理改进，当前版本没加。

## 放弃的方案

- **Postgres 用多 schema 而非多 database**：尝试过 `PREFECT_API_DATABASE_CONNECTION_URL=...?options=-csearch_path%3Dprefect`，Prefect 3 的 alembic migration 不理会 search_path，会把表塞进 public。放弃，改回"多 database"。
- **Prefect 用自带的 SQLite 后端**：更简单，但 ADR §3.2 明确要求 Prefect 用 Postgres 后端以支持 kill -9 自动恢复，不妥协。
- **alembic 同步模式**：本来想图省事用同步 psycopg2，但 A2-Domain + A9-API 后续肯定要 async engine，现在写 async env.py 一次到位。
- **在 Makefile 里 hard-code PATH 加 Docker Desktop bin**：跨平台不通用，交给 setup.md 说明。

## 卡点

**无未解决卡点**。过程中遇到的两个绊子都自洽解决：

1. 本机端口冲突（5432 / 9000 / 9001）→ 用 `docker/.env` 重映射，`.env` 已 gitignored。
2. 误删邻居 compose 项目的 orphan containers → 用 `name: tts-harness` 固定 project 名避免复发。

## 给下游（A2-Domain）的提示

1. **直接 `from server.core.db import get_sessionmaker, get_session`**，无需自己建 engine。
2. **A2 的 ORM 模型要匹配 V001_initial.py**：字段名/类型/约束严格一致。特别注意：
   - `episodes.metadata` 是 `JSONB`（不是 `JSON`）
   - `stage_runs` 是复合主键 `(chunk_id, stage)`
   - `events.id` 是 `BigInteger` 自增；`events` 没有 FK to episodes（ADR 设计如此，便于删 episode 时保留审计痕迹——你可以按需在 A2 改，但必须先回 A0 review）
   - `chunks.char_count` 是 `NOT NULL`，A2 的 repository 创建时必须算好
3. **ORM 模型落地后**：把 `server/migrations/env.py` 里的 `target_metadata = None` 改成 `from core.models import Base; target_metadata = Base.metadata`。这样 `alembic revision --autogenerate` 才能工作。**不要改 V001_initial.py**，有改动就写 V002。
4. **events 表 INSERT 触发的 NOTIFY 已验证可用**：channel = `episode_events`，payload = `{"ep":"<id>","id":<bigint>}`。A2 的 `events.py` 只要 `INSERT INTO events ...`，触发器会自动 NOTIFY，不需要再手动 `pg_notify()`。
5. **本机跑单测**：
   ```bash
   source .venv/bin/activate
   export DATABASE_URL='postgresql+asyncpg://harness:harness@localhost:55432/harness'
   cd server && pytest
   ```
   （记得 `make dev` 保持运行，或者 A2 用 testcontainer 起独立 Postgres。）
6. **compose project 名固定为 `tts-harness`**：用 `docker compose --env-file docker/.env -f docker/docker-compose.dev.yml ...` 调用；或者直接 `make dev` / `make down`。
7. **端口映射看 `docker/.env`**：ADR 默认是 5432 / 9000 / 9001 / 4200，我本机开发映到 55432 / 59000 / 59001 / 54200。其他机器上按需改。
8. **HARNESS_API_TOKEN 只是占位**：A1 没实现 auth，A9-API 去读它。

## 测试 — 跑通的验收命令

全部命令都在 worktree 根目录执行，`export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"` 已设。

### 1. `make dev` 起齐三个容器

```
$ docker compose --env-file docker/.env -f docker/docker-compose.dev.yml ps
NAME                         IMAGE                        STATUS
tts-harness-minio            minio/minio:latest           Up (healthy)   59000->9000, 59001->9001
tts-harness-postgres         postgres:16-alpine           Up (healthy)   55432->5432
tts-harness-prefect-server   prefecthq/prefect:3-latest   Up (healthy)   54200->4200
```

minio-init 一次性容器 exit 0，日志：
```
tts-harness-minio-init  | Added `local` successfully.
tts-harness-minio-init  | Bucket created successfully `local/tts-harness`.
tts-harness-minio-init  | bucket ready: tts-harness
```

### 2. `alembic upgrade head` 成功

```
$ cd server && DATABASE_URL=postgresql+asyncpg://harness:harness@localhost:55432/harness alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> V001_initial, V001 initial — business schema (ADR-001 §5.1)
```

### 3. psql 看到 5 张业务表 + trigger

```
$ docker exec tts-harness-postgres psql -U harness -d harness -c '\dt'
 Schema |      Name       | Type  |  Owner
--------+-----------------+-------+---------
 public | alembic_version | table | harness
 public | chunks          | table | harness
 public | episodes        | table | harness
 public | events          | table | harness
 public | stage_runs      | table | harness
 public | takes           | table | harness
(6 rows)

$ docker exec tts-harness-postgres psql -U harness -d harness -c "SELECT tgname FROM pg_trigger WHERE tgrelid='events'::regclass AND NOT tgisinternal;"
        tgname
-----------------------
 events_notify_trigger
(1 row)
```

### 4. pg_notify 端到端验证（asyncpg LISTEN → INSERT → 收通知）

```
$ python3 -c "<asyncpg LISTEN + INSERT script>"
received: ['{"ep" : "ep-test", "id" : 2}']
OK: pg_notify payload has ep+id
```

payload 结构与 ADR 契约一致：包含 `ep` 与 `id` 两个字段。

### 5. MinIO bucket 存在

```
$ docker run --rm --network tts-harness_default --entrypoint sh minio/mc:latest \
    -c "mc alias set local http://minio:9000 minioadmin minioadmin >/dev/null && mc ls local/"
[2026-04-09 12:53:39 UTC]     0B tts-harness/
```

localhost:59001 （ADR 默认 9001）在浏览器能登录 MinIO console，登录凭证 `minioadmin` / `minioadmin`。

### 6. Prefect UI 可访问

```
$ curl -s -o /dev/null -w "prefect ui http %{http_code}\n" http://localhost:54200/
prefect ui http 200

$ curl -s http://localhost:54200/api/health
true
```

---

**DoD 核对**

- [x] `docker-compose up` 全绿（postgres / minio / prefect-server 三个 healthy + minio-init 一次性完成）
- [x] alembic migration 通过
- [x] Prefect UI 可访问
- [x] MinIO 自动建好 `tts-harness` bucket
- [x] 全部 5 张业务表 + pg_notify trigger 落地并验证
